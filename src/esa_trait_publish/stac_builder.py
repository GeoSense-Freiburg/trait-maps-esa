"""Small utilities to build a STAC Collection and Items from raster maps.

This module wires together filename parsing, trait/stat metadata and raster
metadata to create a minimal, valid pystac Collection and Items. The
implementation is intentionally small and easy to extend with ESA OSC-specific
fields later.
"""

from pathlib import Path
from typing import Dict, Iterable, List, Optional, Callable
import datetime

import pystac
import json as _json

from .config import (
    get_collection_config,
    COG_MEDIA_TYPE,
    ASSET_BASE_HREF,
    ZENODO_FILE_BASE_URL,
    OSC_EXTENSION,
    PROJECTION_EXTENSION,
    OSC_TYPE,
    OSC_STATUS,
    OSC_PROJECT,
    SCIENTIFIC_EXTENSION,
    DOI,
    DOI_URL,
    SCIENTIFIC_CITATION,
    PUBLISHED_DATE,
    KEYWORDS,
    PROVIDERS,
    ROOT_HREF,
)

from .filename_parser import parse_filename
from .raster_metadata import extract_raster_metadata
from .trait_metadata import (
    load_trait_metadata,
    load_stat_metadata,
    build_metadata_record,
)


def create_item_from_raster(
    raster_path: Path,
    trait_mapping: Dict,
    stat_mapping: Dict,
    base_asset_href: Optional[str] = None,
    asset_href_resolver: Optional[Callable[[Path], str]] = None,
) -> pystac.Item:
    """Create a pystac.Item for a single raster file.

    Args:
        raster_path: path to a GeoTIFF/COG
        trait_mapping: loaded trait mapping JSON (dict)
        stat_mapping: loaded statistic mapping JSON (dict)

    Returns:
        pystac.Item: item describing the raster

    Raises:
        RuntimeError: if raster metadata cannot be read or item cannot be created
    """
    raster_path = Path(raster_path)

    # 1. parse filename
    parsed = parse_filename(raster_path)

    # 2. extract raster metadata (may raise)
    rast_meta = extract_raster_metadata(raster_path)

    # 3. build merged metadata record
    record = build_metadata_record(parsed, trait_mapping, stat_mapping)

    # merge raster metadata into properties
    properties = {
        "trait_id": record.get("trait_id"),
        "trait_short_name": record.get("trait_short_name"),
        "trait_long_name": record.get("trait_long_name"),
        "trait_unit": record.get("trait_unit"),
        "stat_id": record.get("stat_id"),
        "stat_name": record.get("stat_name"),
        # raster-derived fields
        "crs": rast_meta.get("crs"),
        "width": rast_meta.get("width"),
        "height": rast_meta.get("height"),
        "nodata": rast_meta.get("nodata"),
        "dtype": rast_meta.get("dtype"),
        "resolution": rast_meta.get("resolution"),
    }

    # Human-readable title and description to improve catalog UX
    try:
        properties.setdefault("title", build_item_title(record.get("trait_long_name"), record.get("stat_name")))
        properties.setdefault("description", build_item_description(record.get("trait_long_name"), record.get("stat_name")))
    except Exception:
        # non-fatal; leave properties unchanged on error
        pass

    # TODO: add OSC-specific properties (extensions) here when available

    # stable id derived from stem
    item_id = parsed.get("stem") or raster_path.stem

    # Use WGS84 geometry and bbox when available. If a WGS84 geometry can be
    # created from raster bounds, set geometry and top-level bbox accordingly.
    # Otherwise, leave geometry None and do not set a top-level bbox (STAC
    # requires bbox/geometry to be WGS84).
    wgs_bbox = rast_meta.get("bbox")
    geometry = rast_meta.get("geometry")
    dt = None

    # For STAC core: set top-level bbox and datetime handling.
    # These maps are static prediction products without an observation time
    # axis. The publication date is product-level metadata and belongs on the
    # Collection (see `published` in collection.extra_fields). Therefore each
    # Item must NOT claim an observation instant or interval. Set the item's
    # top-level `datetime` to null and do not include `start_datetime`/
    # `end_datetime`.
    # Only include bbox when we have a valid WGS84 geometry (to avoid
    # including projected coordinates in top-level bbox). If geometry is
    # present, set bbox to the WGS84 bbox; otherwise leave bbox None.
    item_bbox = wgs_bbox if geometry is not None else None

    # pystac requires start/end datetimes when datetime is None. Use an
    # internal placeholder interval to satisfy the library, but these keys
    # will be removed when the Item is serialized to JSON so published Items
    # do not claim an observation interval.
    start_end_placeholder = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)

    # Use publication date as the item's datetime (product publication /
    # version timestamp). The product itself has no observation time axis;
    # the datetime here reflects the publication timestamp.
    try:
        published_dt = datetime.datetime.fromisoformat(PUBLISHED_DATE.replace("Z", "+00:00"))
    except Exception:
        published_dt = start_end_placeholder

    item = pystac.Item(
        id=item_id,
        geometry=geometry,
        bbox=item_bbox,
        datetime=published_dt,
        # keep in-memory start/end placeholders for pystac but these will not
        # be serialized into the published JSON
        start_datetime=start_end_placeholder,
        end_datetime=start_end_placeholder,
        properties=properties,
    )

    # add asset
    # Resolve asset href: allow hosted URLs for publication while preserving
    # local absolute paths for debugging when no base is provided.
    # Preferred: callers can provide `asset_href_resolver` (callable) or a
    # simple `base_asset_href` string. If both are provided, resolver wins.
    # Determine asset href: resolver wins, otherwise build from explicit
    # base_asset_href or the configured Zenodo base URL, with a local path
    # fallback for debugging.
    if asset_href_resolver is not None:
        href = asset_href_resolver(raster_path)
    else:
        href = build_asset_href(raster_path, base=base_asset_href)

    media_type = COG_MEDIA_TYPE
    # Build a human-readable asset title from trait/stat where possible
    try:
        asset_title = build_item_title_short(record.get("trait_long_name"), record.get("stat_name")) + " Raster"
    except Exception:
        asset_title = "Raster"

    asset = pystac.Asset(href=href, media_type=media_type, roles=["data"], title=asset_title)
    item.add_asset("data", asset)

    # Defensive check: ensure the asset was added
    if "data" not in (item.assets or {}):
        raise RuntimeError(f"Item {item_id} missing required 'data' asset (href={href})")

    # store projected/native spatial metadata in properties using extension-
    # friendly keys so we don't expose projected coordinates in STAC core.
    # Keep keys simple and easy to map to proj extension later.
    native_bbox = rast_meta.get("native_bbox")
    if rast_meta.get("crs") is not None:
        # prefer an EPSG int if present; write as proj:code (string) per projection
        # extension (
        try:
            epsg = int(rast_meta.get("crs"))
            properties.setdefault("proj:code", f"EPSG:{epsg}")
        except Exception:
            # if it's already a string or non-int, fall back to string form
            properties.setdefault("proj:code", str(rast_meta.get("crs")))
    if native_bbox:
        properties.setdefault("proj:bbox", native_bbox)
    # update properties on the item
    item.properties.update(properties)

    # Ensure the projection extension is declared on the Item so tools that
    # understand the projection extension can parse `proj:code` and `proj:bbox`.
    item_exts = list(item.stac_extensions or [])
    if PROJECTION_EXTENSION not in item_exts:
        item_exts.append(PROJECTION_EXTENSION)
    item.stac_extensions = item_exts

    return item


def build_asset_href(raster_path: Path, base: Optional[str] = None) -> str:
    """Return an asset href built from a base URL + filename or a local path.

    Priority for base: explicit `base` argument, configured `ZENODO_FILE_BASE_URL`,
    configured `ASSET_BASE_HREF`. If no base is available, falls back to
    local absolute path (useful for debugging).
    """
    chosen = base
    if not chosen and ZENODO_FILE_BASE_URL:
        chosen = ZENODO_FILE_BASE_URL
    if not chosen and ASSET_BASE_HREF and ASSET_BASE_HREF != "REPLACE_WITH_ZENODO_FILE_BASE_URL":
        chosen = ASSET_BASE_HREF

    if chosen:
        return chosen.rstrip("/") + "/" + raster_path.name
    return str(raster_path.resolve())


def build_collection_summaries(items: Iterable[pystac.Item]) -> Dict[str, List[str]]:
    """Build collection-level summaries by aggregating item properties.

    Returns a dict suitable for assigning to ``collection.summaries`` where
    each key maps to a list of unique, sorted, non-empty values.
    """
    fields = ["trait_short_name", "trait_unit", "stat_name", "proj:code"]
    accum = {k: [] for k in fields}

    for item in items:
        props = item.properties or {}
        for k in fields:
            v = props.get(k)
            if v is None:
                continue
            # accept lists or scalar values
            if isinstance(v, (list, tuple)):
                candidates = list(v)
            else:
                candidates = [v]

            for cand in candidates:
                if cand is None:
                    continue
                s = str(cand).strip()
                if s == "":
                    continue
                if s not in accum[k]:
                    accum[k].append(s)

    # sort values case-insensitively to give a stable, readable ordering
    summaries: Dict[str, List[str]] = {}
    for k, vals in accum.items():
        if not vals:
            continue
        summaries[k] = sorted(vals, key=lambda x: x.lower())

    return summaries


def build_item_assets() -> Dict[str, object]:
    """Return a canonical item_assets mapping for the Collection.

    The returned structure mirrors the STAC `item_assets` convention and is
    also injected into collection.extra_fields under the same key for JSON
    compatibility with tools that expect it there.
    """
    return {
        "data": {
            "type": COG_MEDIA_TYPE,
            "roles": ["data"],
            "title": "Cloud-Optimized GeoTIFF trait raster",
        }
    }


def _format_stat_label(stat_name: Optional[str]) -> str:
    """Return a human-friendly, title-cased label for a statistic name."""
    if not stat_name:
        return ""
    mapping = {
        "mean": "Mean",
        "median": "Median",
        "cv": "Coefficient of Variation",
    }
    s = str(stat_name).strip().lower()
    return mapping.get(s, s.title())


def build_item_title(trait_long_name: Optional[str], stat_name: Optional[str]) -> str:
    """Build a readable item title.

    Format: "{Trait Long Name} {StatLabel} — Global 1 km Plant Trait Map"
    Prefer trait_long_name; fall back to a short name if missing. Title-case the
    final value for readability.
    """
    trait = (trait_long_name or "Trait").strip()
    stat_label = _format_stat_label(stat_name)
    pieces = [trait]
    if stat_label:
        pieces.append(stat_label)
    main = " ".join(pieces).title()
    return f"{main} — Global 1 km Plant Trait Map"


def build_item_description(trait_long_name: Optional[str], stat_name: Optional[str]) -> str:
    """Build a readable item description.

    Example:
      "Global 1 km map of community-weighted mean leaf length derived from GBIF, sPlot, TRY, and Earth observation predictors."

    The description always mentions global extent, 1 km resolution, community-weighting
    and the main source datasets. The wording adapts slightly for CV vs. mean/median.
    """
    trait = (trait_long_name or "trait").strip()
    # lower-case the trait for fluent sentence grammar
    trait_lc = trait.lower()

    s = (stat_name or "").strip().lower()
    if s == "cv":
        stat_phrase = "coefficient of variation of"
    elif s in ("mean", "median"):
        stat_phrase = s
    elif s:
        stat_phrase = s
    else:
        stat_phrase = "statistic"

    # use community-weighted phrasing for central tendency statistics
    if s in ("mean", "median"):
        cw_phrase = "community-weighted"
    else:
        cw_phrase = "community-weighted"

    description = (
        f"Global 1 km map of {cw_phrase} {stat_phrase} {trait_lc} "
        "derived from GBIF, sPlot, TRY, and Earth observation predictors."
    )
    # Capitalize first letter only for readability in properties
    return description[0].upper() + description[1:]


def build_item_title_short(trait_long_name: Optional[str], stat_name: Optional[str]) -> str:
    """Build a short human-readable title used for asset titles.

    Example: "Leaf Length Mean"
    """
    trait = (trait_long_name or "Trait").strip()
    stat_label = _format_stat_label(stat_name)
    pieces = [trait]
    if stat_label:
        pieces.append(stat_label)
    return " ".join(pieces).title()


def apply_osc_collection_fields(collection: pystac.Collection) -> pystac.Collection:
    """Apply OSC metadata to a Collection.

    This sets the OSC extension URL on `stac_extensions` and writes the
    minimal OSC extra fields required by ESA: `osc:type`, `osc:status` and
    `osc:project` (string).
    """
    # Ensure extra_fields exists and is a dict
    ef = collection.extra_fields or {}

    # Required OSC fields per user request
    ef["osc:type"] = OSC_TYPE
    ef["osc:status"] = OSC_STATUS
    ef["osc:project"] = OSC_PROJECT

    # attach back
    collection.extra_fields = ef

    # register the OSC extension URL (official schema) for discoverability
    stac_exts = list(collection.stac_extensions or [])
    if OSC_EXTENSION not in stac_exts:
        stac_exts.append(OSC_EXTENSION)
    # Do not add scientific extension here; create_collection will opt-in when
    # constructing the final collection object so we can keep extension
    # placement explicit and isolated.
    collection.stac_extensions = stac_exts

    return collection


def create_collection() -> pystac.Collection:
    """Create a base STAC Collection for the global plant trait maps.

    The collection uses a placeholder license and includes a description with
    dataset context and DOI. Update license and links from authoritative
    Zenodo/metadata when available.
    """
    cfg = get_collection_config()
    spatial = pystac.SpatialExtent([cfg.get("spatial_extent")])
    temporal = pystac.TemporalExtent([[None, None]])
    extent = pystac.Extent(spatial=spatial, temporal=temporal)
    description = cfg.get("description")

    coll = pystac.Collection(
        id=cfg.get("id"),
        description=description,
        extent=extent,
        title=cfg.get("title"),
        license=cfg.get("license"),  # TODO: replace with authoritative Zenodo license metadata
    )

    # Apply OSC placeholder fields to make the collection scaffold-ready for
    # ESA Open Science Catalog ingestion. This is intentionally minimal and
    # can be expanded when final OSC requirements are determined.
    coll = apply_osc_collection_fields(coll)

    # Add scientific extension and collection-level scientific metadata.
    sc_exts = list(coll.stac_extensions or [])
    if SCIENTIFIC_EXTENSION not in sc_exts:
        sc_exts.append(SCIENTIFIC_EXTENSION)
    coll.stac_extensions = sc_exts

    # Keywords
    coll.keywords = list(KEYWORDS)

    # Providers: convert simple dicts into pystac Provider objects if possible
    providers = []
    for p in PROVIDERS:
        try:
            provider = pystac.Provider(name=p.get("name"), roles=p.get("roles"))
            providers.append(provider)
        except Exception:
            # Fall back to raw dict; pystac will accept list of dicts in some versions
            providers.append(p)
    coll.providers = providers

    # Scientific citation metadata (extension-friendly keys)
    ef = coll.extra_fields or {}
    ef.setdefault("sci:doi", DOI)
    ef.setdefault("sci:citation", SCIENTIFIC_CITATION)
    # publication date
    ef.setdefault("published", PUBLISHED_DATE)
    coll.extra_fields = ef

    # add placeholder links (use Link constructor for broad pystac compatibility)
    # Do not add a 'root' link pointing to project root; it may not resolve
    # to a STAC object when catalogs are normalized. Add only self and
    # describedby links.
    # Use a relative self link and add DOI links (describedby and cite-as)
    # Add self and describedby links. We do not attach the `root` link as a
    # pystac.Link here because some pystac versions attempt to resolve root
    # link targets when converting to dict. Instead the root link is injected
    # during JSON sanitization in `save_collection` to keep serialized output
    # free of absolute filesystem paths.
    coll.add_link(pystac.Link("self", "./collection.json", media_type="application/json"))
    coll.add_link(pystac.Link("describedby", DOI_URL, media_type="text/html", title="Zenodo record"))
    coll.add_link(pystac.Link("cite-as", DOI_URL, media_type="text/html", title="Dataset DOI"))

    return coll


def build_collection_from_directory(
    maps_dir: Path,
    trait_metadata_path: Path,
    stat_metadata_path: Path,
    base_asset_href: Optional[str] = None,
    asset_href_resolver: Optional[Callable[[Path], str]] = None,
) -> pystac.Collection:
    """Build a STAC Collection populated from rasters in `maps_dir`.

    Args:
        maps_dir: directory containing raster products (*.tif, *.tiff)
        trait_metadata_path: path to trait_mapping.json
        stat_metadata_path: path to trait_stat_mapping.json

    Returns:
        populated pystac.Collection
    """
    maps_dir = Path(maps_dir)
    trait_map = load_trait_metadata(Path(trait_metadata_path))
    stat_map = load_stat_metadata(Path(stat_metadata_path))

    collection = create_collection()

    # discover raster files
    files: List[Path] = []
    files.extend(sorted(maps_dir.glob("*.tif")))
    files.extend(sorted(maps_dir.glob("*.tiff")))
    files = sorted(set(files), key=lambda p: p.name)

    for f in files:
        # be explicit about errors when reading individual rasters
        item = create_item_from_raster(
            f,
            trait_map,
            stat_map,
            base_asset_href=base_asset_href,
            asset_href_resolver=asset_href_resolver,
        )
        collection.add_item(item)

    return collection


def save_collection(collection: pystac.Collection, output_dir: Path) -> int:
    """Save the collection and contained items to `output_dir` as a self-contained catalog.

    Args:
        collection: collection to save
        output_dir: directory to write the collection to
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Flat layout: collection.json at output_dir, items in output_dir/items/*.json
    items_dir = output_dir / "items"
    items_dir.mkdir(parents=True, exist_ok=True)

    collection_path = output_dir / "collection.json"

    # Capture items up-front. Some pystac Collection implementations store
    # items only as Link targets (link -> Item). Clearing collection.links
    # before capturing items will drop those references and make
    # `collection.get_items()` return an empty iterator. Capture the items
    # first so we can write them even if links are replaced below.
    items_to_write = list(collection.get_items())

    # Generate and attach collection summaries and item_assets based on the
    # current set of items. This improves discoverability and provides a
    # single place to document common item assets.
    try:
        summaries = build_collection_summaries(items_to_write)
        if summaries:
            # pystac expects a Summaries object; wrap the dict accordingly
            collection.summaries = pystac.Summaries(summaries)
    except Exception:
        # Non-fatal: summaries are an enhancement, not required for writing
        pass

    try:
        # Inject item_assets into extra_fields so it is serialized with the
        # collection. Some tooling expects `item_assets` at the collection
        # level in extra_fields; including it here improves interoperability.
        ef = collection.extra_fields or {}
        ef.setdefault("item_assets", build_item_assets())
        collection.extra_fields = ef
    except Exception:
        pass

    # Clear existing collection links to avoid duplicates and set root/self/describe
    collection.links = []
    coll_title = get_collection_config().get("title")
    # Self and describedby links. The root link is injected at JSON
    # serialization time to avoid pystac attempting to resolve the target.
    collection.add_link(pystac.Link("self", "./collection.json", media_type="application/json"))
    if get_collection_config().get("zenodo_doi_url"):
        doi = get_collection_config().get("zenodo_doi_url")
        # keep describedby for the DOI landing page
        collection.add_link(pystac.Link("describedby", doi, media_type="text/html"))
        # add a canonical cite-as relation pointing to the DOI (configurable)
        collection.add_link(pystac.Link("cite-as", doi, media_type="text/html", title="Dataset DOI"))

    # We'll accumulate item links for the collection and write items manually
    collection_item_links: List[dict] = []

    for item in items_to_write:
        # remove temporal keys from properties if present (they belong top-level)
        for tf in ("start_datetime", "end_datetime", "datetime"):
            if tf in (item.properties or {}):
                item.properties.pop(tf, None)

        # Ensure human-readable title/description are present on the Item
        # object so they are included by pystac when converting to dict.
        try:
            iprops = item.properties or {}
            if "title" not in iprops:
                iprops["title"] = build_item_title(iprops.get("trait_long_name"), iprops.get("stat_name"))
            if "description" not in iprops:
                iprops["description"] = build_item_description(iprops.get("trait_long_name"), iprops.get("stat_name"))
            item.properties = iprops
        except Exception:
            pass

        # ensure bbox exists at top-level; if missing try to extract from asset href
        if not item.bbox:
            assets = item.assets or {}
            primary = assets.get("data") or (next(iter(assets.values()), None) if assets else None)
            if primary and getattr(primary, "href", None):
                href = getattr(primary, "href")
                try:
                    rast_meta = extract_raster_metadata(Path(href))
                    bb = rast_meta.get("bbox")
                    if bb:
                        item.bbox = bb
                except Exception:
                    # leave as-is if we cannot read the href (hosted URL etc.)
                    pass

        # Build the item JSON dict and replace its links with clean relative ones
        item_json = item.to_dict()

        # Ensure temporal fields are top-level (not inside properties).
        # These are static products without an observation datetime. Collection-level
        # publication metadata is stored on the Collection (see `published`).
        # Remove any temporal keys present inside properties (defensive)
        raw_props = item_json.get("properties", {}) or {}
        props = {k: v for k, v in raw_props.items() if k not in ("datetime", "start_datetime", "end_datetime")}

        # Ensure title/description are present in the serialized properties.
        # Build them from available metadata with a safe fallback.
        trait_long = props.get("trait_long_name") or props.get("trait_short_name") or ""
        stat_nm = props.get("stat_name") or ""

        title_val = None
        desc_val = None
        try:
            title_val = build_item_title(trait_long, stat_nm)
        except Exception:
            title_val = None
        try:
            desc_val = build_item_description(trait_long, stat_nm)
        except Exception:
            desc_val = None

        # Fallback simple formatting if helpers failed or returned empty
        if not title_val:
            stat_label = _format_stat_label(stat_nm) or ""
            title_main = (trait_long or "Trait").strip().title()
            if stat_label:
                title_val = f"{title_main} {stat_label} — Global 1 km Plant Trait Map"
            else:
                title_val = f"{title_main} — Global 1 km Plant Trait Map"

        if not desc_val:
            trait_lc = (trait_long or "trait").strip().lower()
            s = (stat_nm or "").strip().lower()
            stat_phrase = "statistic"
            if s == "cv":
                stat_phrase = "coefficient of variation of"
            elif s in ("mean", "median"):
                stat_phrase = s
            desc_val = (
                f"Global 1 km map of community-weighted {stat_phrase} {trait_lc} "
                "derived from GBIF, sPlot, TRY, and Earth observation predictors."
            )

        # Finally set the properties (do not overwrite existing user-supplied values)
        if title_val and "title" not in props:
            props["title"] = title_val
        if desc_val and "description" not in props:
            props["description"] = desc_val

        item_json["properties"] = props

        # Final safety: ensure title/description exist in the serialized
        # properties (overwrite only when empty) so all written Items are
        # consistently human-readable.
        try:
            t = build_item_title(props.get("trait_long_name"), props.get("stat_name"))
            d = build_item_description(props.get("trait_long_name"), props.get("stat_name"))
            if t:
                item_json["properties"]["title"] = t
            if d:
                item_json["properties"]["description"] = d
        except Exception:
            pass

        # Set top-level temporal field to the publication date (product
        # publication/version timestamp). These products have no observation
        # time axis; item datetime therefore reflects publication, not
        # observation.
        item_json["datetime"] = PUBLISHED_DATE
        item_json.pop("start_datetime", None)
        item_json.pop("end_datetime", None)

        # desired links for item (relative to items/ directory)
        # Compute root href relative to the items directory. If ROOT_HREF is
        # already a relative path to collection.json this will typically be
        # "../collection.json". Otherwise attempt a simple fallback.
        if ROOT_HREF.startswith("./"):
            root_rel = "../" + ROOT_HREF.lstrip("./")
        else:
            # if ROOT_HREF is absolute or points elsewhere, fall back to the
            # configured ROOT_HREF value (it is the best authoritative root).
            root_rel = ROOT_HREF

        item_links = [
            {"rel": "root", "href": root_rel, "type": "application/json", "title": coll_title},
            {"rel": "parent", "href": "../collection.json", "type": "application/json", "title": coll_title},
            {"rel": "collection", "href": "../collection.json", "type": "application/json", "title": coll_title},
            {"rel": "self", "href": f"./{item.id}.json", "type": "application/geo+json"},
        ]

        item_json["links"] = item_links

        # write item to items/{id}.json
        item_path = items_dir / f"{item.id}.json"
        try:
            item_path.write_text(_json.dumps(item_json, indent=2), encoding="utf-8")
        except Exception as exc:  # pragma: no cover - IO/runtime environment errors
            raise RuntimeError(f"Failed to write item {item.id} to {item_path}: {exc}")

        # add collection -> item link (relative path)
        collection_item_links.append({"rel": "item", "href": f"./items/{item.id}.json", "type": "application/geo+json"})

    # attach collected item links to collection (after items written)
    for l in collection_item_links:
        collection.add_link(pystac.Link(l["rel"], l["href"], media_type=l.get("type")))

    # write collection.json
    coll_json = collection.to_dict()

    # Sanitize links in the serialized collection JSON to avoid absolute
    # filesystem paths leaking into the output. Ensure `self` is a relative
    # ./collection.json with type application/json and keep describedby as HTML.
    links = coll_json.get("links", []) or []
    sanitized_links = []
    # Inject a root link based on configured ROOT_HREF. If ROOT_HREF is a
    # simple local path (e.g. ./collection.json) make it relative in the
    # serialized output; otherwise use the configured value.
    if ROOT_HREF.startswith("./"):
        root_href_serialized = ROOT_HREF
    else:
        root_href_serialized = ROOT_HREF
    # build root link dict now so it appears first
    root_link_dict = {"rel": "root", "href": root_href_serialized, "type": "application/json"}

    for l in links:
        rel = l.get("rel")
        # skip any existing root links (we inject a canonical one)
        if rel == "root":
            continue
        if rel == "self":
            sanitized_links.append({"rel": "self", "href": "./collection.json", "type": "application/json"})
        elif rel == "describedby":
            # use configured DOI landing page when available
            sanitized_links.append({"rel": "describedby", "href": get_collection_config().get("zenodo_doi_url"), "type": "text/html"})
        else:
            # keep other links (item links should already be relative)
            sanitized_links.append(l)
    # put root first, then the rest
    coll_json["links"] = [root_link_dict] + sanitized_links

    collection_path.write_text(_json.dumps(coll_json, indent=2), encoding="utf-8")

    return len(items_to_write)
