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
import logging
import re

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
    RASTER_EXTENSION,
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


def infer_product_status_from_path(path: Path) -> str:
    """Infer product status from a path string.

    Looks for known status tokens in the path. Raises ValueError if unknown
    and not allowed.
    """
    allowed = {"analysis-ready", "experimental", "hydraulic"}
    s = str(path).lower()
    for token in allowed:
        if token in s:
            return token
    raise ValueError(f"Could not infer product status from path: {path}")


def load_existing_collection(output_dir: Path) -> Optional[tuple[pystac.Collection, set]]:
    """Load an existing collection.json and return (collection, existing_item_ids).

    existing_item_ids is parsed from the collection.json links to avoid
    resolving items (which may fail if items have datetime=None). Returns
    None when no collection.json exists or on fatal errors.
    """
    coll_path = Path(output_dir) / "collection.json"
    if not coll_path.exists():
        return None
    try:
        # parse raw JSON to extract item hrefs without resolving linked items
        raw = _json.loads(Path(coll_path).read_text(encoding="utf-8"))
        links = raw.get("links", []) or []
        ids = set()
        for l in links:
            if l.get("rel") == "item" and l.get("href"):
                href = l.get("href")
                name = Path(href).stem
                ids.add(name)
        # load collection object (pystac) for merging metadata; avoid iterating items
        coll = pystac.Collection.from_file(str(coll_path))
        return coll, ids
    except Exception:
        return None


def merge_items_into_collection(
    collection: pystac.Collection,
    new_items: List[pystac.Item],
    preserve_existing: bool = True,
    status: Optional[str] = None,
    existing_ids: Optional[set] = None,
) -> pystac.Collection:
    """Merge new_items into collection, trying to avoid ID collisions.

    If an item ID already exists and preserve_existing is True, the item will
    be skipped. If preserve_existing is False and a status is provided, the
    function will attempt to append the status to the item id to disambiguate
    (e.g. itemid_analysis-ready). If a disambiguated id also exists, the item
    is skipped.
    """
    if existing_ids is None:
        # fallback: do not force resolving items; try to read from collection.get_items()
        try:
            existing_ids = {it.id for it in collection.get_items()}
        except Exception:
            existing_ids = set()
    added = 0
    for it in new_items:
        if it.id in existing_ids:
            if preserve_existing:
                print(f"Skipping existing item: {it.id}")
                continue
            # try to disambiguate using status suffix
            if status:
                alt_id = f"{it.id}_{status}"
                if alt_id in existing_ids:
                    print(f"Skipping item; both {it.id} and {alt_id} exist")
                    continue
                print(f"ID conflict for {it.id}; adding as {alt_id}")
                it.id = alt_id
                collection.add_item(it)
                existing_ids.add(alt_id)
                added += 1
                continue
            print(f"Skipping existing item: {it.id}")
            continue
        collection.add_item(it)
        existing_ids.add(it.id)
        added += 1
    print(f"Added {added} new items to collection {collection.id}")
    return collection


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

    # merge core scientific metadata into properties (keep it minimal)
    properties = {
        "trait_id": record.get("trait_id"),
        "trait_short_name": record.get("trait_short_name"),
        "trait_long_name": record.get("trait_long_name"),
        "trait_unit": record.get("trait_unit"),
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

    # store projection fields using projection extension keys only
    native_bbox = rast_meta.get("native_bbox")
    if rast_meta.get("crs") is not None:
        try:
            epsg = int(rast_meta.get("crs"))
            item.properties.setdefault("proj:code", f"EPSG:{epsg}")
        except Exception:
            item.properties.setdefault("proj:code", str(rast_meta.get("crs")))
    if native_bbox:
        item.properties.setdefault("proj:bbox", native_bbox)
    # proj:transform from raster metadata (list of 6 numeric values)
    try:
        tr = rast_meta.get("transform")
        if tr and isinstance(tr, (list, tuple)):
            # ensure we have numeric values and exactly 6 elements
            tvals = [float(x) for x in list(tr)[:6]]
            item.properties.setdefault("proj:transform", tvals)
    except Exception:
        pass
    # proj:shape and proj:transform if available
    try:
        if rast_meta.get("width") and rast_meta.get("height"):
            item.properties.setdefault("proj:shape", [rast_meta.get("height"), rast_meta.get("width")])
    except Exception:
        pass

    # keep lightweight user-facing GSD (ground sampling distance) as integer meters
    try:
        res = rast_meta.get("resolution")
        if res and isinstance(res, (list, tuple)) and res[0]:
            item.properties.setdefault("gsd", int(round(abs(res[0]))))
    except Exception:
        pass

    # attach compact dataset tags (only selected fields). If compact_tags is
    # not provided try the raw dataset tags extracted from the TIFF. Ensure we
    # do not include any transform/resolution/crs/affine strings — those belong
    # only under proj:* keys.
    try:
        compact = rast_meta.get("compact_tags") or rast_meta.get("tags") or {}
        # drop any keys that are transform-like to avoid duplication
        banned_tag_keys = {"transform", "affine", "resolution", "crs", "width", "height", "spatial_extent"}
        compact_filtered = {k: v for k, v in compact.items() if k.lower() not in banned_tag_keys}
        # Only include genuinely item-specific scientific metadata in dataset_tags.
        # Do NOT include contact/provenance fields here (they belong on the Collection).
        allowed = {"model_performance", "pfts", "source_creation_date", "usage_notes", "keywords"}#"language", "geospatial_units"
        dataset_tags = {k: v for k, v in compact_filtered.items() if k in allowed}
        if dataset_tags:
            item.properties.setdefault("dataset_tags", dataset_tags)
    except Exception:
        pass

    # Build raster:bands entries and attach them to the asset (assets.data)
    try:
        bands_meta = rast_meta.get("bands", [])
        if bands_meta:
            raster_bands = []
            for b in bands_meta:
                idx = b.get("band_index")
                desc = b.get("description")
                dlow = (desc or "").lower()
                if "coefficient of variation" in dlow or " cv" in dlow:
                    name = "coefficient_of_variation"
                elif "area of applicability" in dlow:
                    name = "area_of_applicability"
                elif "mean" in dlow or "(mean)" in (desc or ""):
                    name = "trait_mean"
                else:
                    name = f"band_{idx}"

                unit = b.get("unit") or None
                # apply unit heuristics when missing
                if not unit:
                    if idx == 1:
                        unit = record.get("trait_unit") or "unitless"
                    elif idx == 2:
                        unit = "%"
                    elif idx == 3:
                        unit = "binary mask"
                    else:
                        unit = "unitless"

                rb = {
                    "name": name,
                    "description": desc,
                    "data_type": b.get("dtype"),
                    "nodata": b.get("nodata"),
                    "unit": unit,
                    "sampling": "area",
                }
                # include scale/offset when present
                if b.get("scale") is not None:
                    rb["scale"] = b.get("scale")
                if b.get("offset") is not None:
                    rb["offset"] = b.get("offset")
                if b.get("tags"):
                    rb["tags"] = b.get("tags")
                if b.get("overviews"):
                    rb["overviews"] = b.get("overviews")
                raster_bands.append(rb)

            # attach to the asset dict (item.assets -> data)
            try:
                # ensure the asset dict exists on the item
                asset_dict = item.assets.get("data")
                # pystac.Asset -> we will ensure serialized JSON contains raster:bands
            except Exception:
                asset_dict = None
            # We'll move raster_bands into the serialized JSON later (in save_collection)
            # to avoid modifying pystac Asset internals here. Store temporarily in properties
            item.properties.setdefault("_raster_bands_tmp", raster_bands)
    except Exception:
        pass

    # Ensure the projection and raster extensions are declared on the Item
    item_exts = list(item.stac_extensions or [])
    if PROJECTION_EXTENSION not in item_exts:
        item_exts.append(PROJECTION_EXTENSION)
    if RASTER_EXTENSION not in item_exts:
        item_exts.append(RASTER_EXTENSION)
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
    fields = ["trait_short_name", "trait_unit", "stat_name", "proj:code", "trait_map:product_status"]
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


# preserve common scientific acronyms in titles/descriptions
ACRONYMS = {"SRL", "SLA", "LMA", "LDMC", "CV"}


def _preserve_acronyms(text: str) -> str:
    if not text:
        return text
    # do not change case globally; preserve original case but fix known
    # acronyms that may have been lower-cased earlier
    t = text
    for a in ACRONYMS:
        # replace case-insensitively when acronym appears as a whole word
        t = re.sub(rf"\b{a.lower()}\b", a, t, flags=re.IGNORECASE)
    return t


# mapping of common tokens to desired capitalization in descriptions/titles
ACRONYM_MAP = {
    "gbif": "GBIF",
    "splot": "sPlot",
    "try": "TRY",
    "srl": "SRL",
    "sla": "SLA",
    "lma": "LMA",
    "ldmc": "LDMC",
    "c:n": "C:N",
    "cn": "C:N",
}


def _restore_acronyms_in_text(text: str) -> str:
    """Replace known acronym tokens in text without changing sentence case.

    This does a case-insensitive whole-word replacement for known tokens and
    returns the adjusted string. It avoids title-casing the entire sentence.
    """
    if not text:
        return text
    out = text
    for k, v in ACRONYM_MAP.items():
        out = re.sub(rf"\b{re.escape(k)}\b", v, out, flags=re.IGNORECASE)
    return out


def _parse_dataset_tags(raw: dict) -> Optional[dict]:
    """Parse raw TIFF dataset tags into a compact dataset_tags object.

    Returns None when no useful tags are found.
    """
    if not raw or not isinstance(raw, dict):
        return None
    out = {}
    # keywords: parse comma separated string into list (lowercase)
    kw = raw.get("keywords") or raw.get("Keywords") or raw.get("KEYWORDS")
    if isinstance(kw, str) and kw.strip():
        parts = [k.strip().lower() for k in kw.split(",") if k.strip()]
        if parts:
            out["keywords"] = parts

    # PFTs
    pfts = raw.get("PFTs") or raw.get("pfts") or raw.get("pft")
    if isinstance(pfts, str) and pfts.strip():
        out["pfts"] = pfts

    # source creation date
    cd = raw.get("creation_date") or raw.get("creationDate") or raw.get("CreationDate")
    if isinstance(cd, str) and cd.strip():
        out["source_creation_date"] = cd

    # model_performance: if it's a JSON string, parse it
    mp = raw.get("model_performance") or raw.get("modelPerformance")
    if isinstance(mp, str) and mp.strip():
        try:
            out_mp = _json.loads(mp)
            out["model_performance"] = out_mp
        except Exception:
            # keep as string if not JSON
            out["model_performance"] = mp
    elif isinstance(mp, dict):
        out["model_performance"] = mp

    # usage notes
    un = raw.get("usage_notes") or raw.get("usageNotes") or raw.get("usage")
    if isinstance(un, str) and un.strip():
        out["usage_notes"] = un

    # additional helpful fields
    lang = raw.get("language") or raw.get("Language")
    if isinstance(lang, str) and lang.strip():
        out["language"] = lang

    # Note: do NOT include contact/author/organization in parsed dataset_tags.
    # These provenance fields are collection-level metadata and should not be
    # duplicated in every Item. Any such keys will be stripped later during
    # sanitization to ensure the collection is authoritative.

    geounits = raw.get("geospatial_units") or raw.get("geospatialUnits")
    if isinstance(geounits, str) and geounits.strip():
        out["geospatial_units"] = geounits

    return out if out else None



def _normalize_trait_unit(trait_unit: Optional[str], trait_long_name: Optional[str]) -> str:
    """Normalize placeholder units like '-' into machine-readable units.

    Heuristic:
    - if trait_unit is '-' or empty: prefer 'count' when trait name suggests a number/count,
      otherwise 'unitless'.
    - otherwise return trait_unit as-is.
    """
    if trait_unit is None:
        trait_unit = ""
    ut = str(trait_unit).strip()
    if ut == "-" or ut == "":
        name = (trait_long_name or "").lower()
        if any(k in name for k in ("number", "count", "density", "per ", "per/", "per-")):
            return "count"
        return "unitless"
    return ut


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
    main = _preserve_acronyms(" ".join(pieces))
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
    # sentence case: lowercase except first letter, but preserve acronyms
    desc = description[0].upper() + description[1:]
    # restore known acronym capitalization
    desc = _restore_acronyms_in_text(desc)
    desc = _preserve_acronyms(desc)
    return desc


def build_item_title_short(trait_long_name: Optional[str], stat_name: Optional[str]) -> str:
    """Build a short human-readable title used for asset titles.

    Example: "Leaf Length Mean"
    """
    trait = (trait_long_name or "Trait").strip()
    stat_label = _format_stat_label(stat_name)
    pieces = [trait]
    if stat_label:
        pieces.append(stat_label)
    return _preserve_acronyms(" ".join(pieces))


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
            # Augment known provider metadata where appropriate (do not mutate global config)
            pcopy = dict(p)
            if pcopy.get("name") and "University of Freiburg" in pcopy.get("name"):
                # ensure a URL is present for the University provider
                pcopy.setdefault("url", "https://geosense.uni-freiburg.de")
            provider = pystac.Provider(name=pcopy.get("name"), roles=pcopy.get("roles"), url=pcopy.get("url"))
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

    # Add authoritative contact/provenance metadata at the collection level.
    # Place under a namespaced custom field to avoid introducing unsupported
    # top-level STAC fields. Tools can still discover this metadata easily.
    contacts = [
        {
            "name": "Daniel Lusk",
            "role": "creator",
            "email": "daniel.lusk@geosense.uni-freiburg.de",
            "organization": "Department for Sensor-based Geoinformatics, University of Freiburg",
        }
    ]
    # Attach under a namespaced key to avoid STAC validation issues with unknown top-level keys
    ef = coll.extra_fields or {}
    ef.setdefault("trait_map:contacts", contacts)
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
    logger = logging.getLogger(__name__)

    def is_valid_raster_file(path: Path) -> bool:
        """Return True for real raster files we should process.

        Rules:
        - only accept names that end exactly with .tif or .tiff (case-insensitive)
        - reject files beginning with '._' (resource forks) or '.' (hidden)
        - require the path to be a regular file
        """
        name = path.name
        # Exclude resource-fork and hidden files
        if name.startswith("._"):
            return False
        if name.startswith("."):
            return False

        # Must be a regular file
        if not path.is_file():
            return False

        nl = name.lower()
        # Only accept exact raster filename endings
        if nl.endswith(".tif") or nl.endswith(".tiff"):
            return True
        return False

    # Iterate directory entries and filter strictly for valid raster files.
    skipped = []
    try:
        for p in maps_dir.iterdir():
            try:
                if is_valid_raster_file(p):
                    files.append(p)
                else:
                    # Debug log skipped files; do not treat as an error.
                    logger.debug("Skipping non-raster or sidecar file: %s", p.name)
                    skipped.append(p.name)
            except Exception:
                # Be defensive: skip problematic entries but log at debug level
                logger.debug("Error inspecting file %s; skipping", str(p), exc_info=True)
                skipped.append(str(p))
    except Exception:
        # If the directory cannot be read, propagate the error so callers see it
        raise

    # Sort deterministically by filename (case-insensitive)
    files = sorted(files, key=lambda p: p.name.lower())

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


def save_collection(
    collection: pystac.Collection,
    output_dir: Path,
    overwrite_items: bool = True,
    additional_items: Optional[List[pystac.Item]] = None,
) -> int:
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

    # Determine items to write. If additional_items is provided (e.g. when
    # extending an existing collection), use that list to avoid resolving
    # existing collection item links which can cause pystac to attempt to
    # load and validate linked item files. Otherwise, capture items from the
    # in-memory collection (fresh build).
    if additional_items is not None:
        items_to_write = list(additional_items)
    else:
        # May trigger resolution when collection contains linked items.
        items_to_write = list(collection.get_items())

    # Generate and attach/merge collection summaries and item_assets based on
    # the new items. When extending an existing collection, merge new summary
    # values with existing collection.summaries if present.
    try:
        new_summaries = build_collection_summaries(items_to_write)
        if new_summaries:
            # merge with existing summaries if available
            try:
                existing = collection.summaries.to_dict() if getattr(collection, "summaries", None) else {}
            except Exception:
                existing = {}
            merged = {}
            # union existing and new values
            for k, v in {**existing, **new_summaries}.items():
                a = list(existing.get(k, [])) if existing else []
                b = list(new_summaries.get(k, [])) if new_summaries else []
                merged_vals = list(dict.fromkeys([*a, *b]))
                if merged_vals:
                    merged[k] = sorted(merged_vals, key=lambda x: x.lower())
            if merged:
                collection.summaries = pystac.Summaries(merged)
    except Exception:
        # Non-fatal
        pass

    try:
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

        # If an existing item file exists and we're preserving existing files,
        # still sanitize its contents to remove raw TIFF metadata and move
        # raster:bands into the asset. We'll read the existing JSON and
        # sanitize it in-place to avoid leaving legacy metadata in the repo.
        item_path = items_dir / f"{item.id}.json"
        if item_path.exists() and not overwrite_items:
            try:
                existing = _json.loads(item_path.read_text(encoding="utf-8"))
                # merge core fields from generated item_json (title/description/links)
                # prefer existing asset href if present
                # sanitize existing file
                # Merge selected properties from in-memory item into existing JSON
                existing_props = existing.get("properties", {}) or {}
                mem_props = item.properties or {}
                # keys we want to ensure exist from the in-memory item when missing
                ensure_keys = ("proj:transform", "proj:code", "proj:bbox", "proj:shape", "gsd", "trait_unit", "title", "description")
                for k in ensure_keys:
                    if k not in existing_props and k in mem_props and mem_props.get(k) is not None:
                        existing_props[k] = mem_props.get(k)
                existing["properties"] = existing_props
                item_json = existing
            except Exception:
                # if reading fails, fall back to generated dict
                item_json = item.to_dict()

        # Sanitize the item JSON thoroughly: helper inlined for clarity
        raw_props = item_json.get("properties", {}) or {}
        props = {k: v for k, v in raw_props.items() if k not in ("datetime", "start_datetime", "end_datetime")}

        # Remove internal-only metadata and conflicting license/rights
        for internal in ("stat_id", "stat_name", "license", "rights"):
            props.pop(internal, None)

        # remove any temporary raster band placeholder and normalize trait unit
        props.pop("_raster_bands_tmp", None)
        if props.get("trait_unit"):
            props["trait_unit"] = _normalize_trait_unit(props.get("trait_unit"), props.get("trait_long_name"))

        # Remove duplicate raster metadata keys that belong in proj:*/assets
        for dup in ("nodata", "dtype", "resolution", "width", "height", "transform", "bbox", "crs"):
            props.pop(dup, None)
        # also drop any affine/transform/resolution-like strings that may have
        # been embedded in dataset_tags or other raw properties
        for tkey in ("transform", "affine", "resolution", "spatial_extent"):
            props.pop(tkey, None)

        # Parse and normalize dataset_tags from any compact tags available
        dataset_tags_raw = props.get("dataset_tags") or raw_props.get("dataset_tags") or {}
        # ensure transform-like keys are removed from dataset_tags
        if isinstance(dataset_tags_raw, dict):
            for tk in ("transform", "affine", "resolution", "crs", "width", "height", "spatial_extent"):
                dataset_tags_raw.pop(tk, None)
        parsed = _parse_dataset_tags(dataset_tags_raw)
        if parsed:
            # Ensure contact/provenance fields are not carried into item-level tags
            for rm in ("author", "contact", "organization"):
                parsed.pop(rm, None)
            props["dataset_tags"] = parsed
        else:
            props.pop("dataset_tags", None)

        # Ensure title/description exist and preserve acronym capitalization
        trait_long = props.get("trait_long_name") or props.get("trait_short_name") or ""
        stat_nm = props.get("stat_name") or ""

        try:
            title_val = _preserve_acronyms(build_item_title(trait_long, stat_nm))
        except Exception:
            title_val = None
        try:
            desc_val = build_item_description(trait_long, stat_nm)
        except Exception:
            desc_val = None

        # Overwrite title/description to ensure consistent casing and acronym preservation
        if title_val:
            props["title"] = _preserve_acronyms(title_val)
        if desc_val:
            props["description"] = _preserve_acronyms(desc_val)

        item_json["properties"] = props

        # Set top-level datetime to publication date and remove temporal placeholders
        item_json["datetime"] = PUBLISHED_DATE
        item_json.pop("start_datetime", None)
        item_json.pop("end_datetime", None)

    # Move raster bands stored temporarily in properties into the data asset
        # Also handle legacy cases where raster:bands may exist in properties
        tmp_bands = None
        if isinstance(raw_props.get("_raster_bands_tmp"), list):
            tmp_bands = raw_props.get("_raster_bands_tmp")
        elif isinstance(props.get("raster:bands"), list):
            tmp_bands = props.get("raster:bands")
            # remove it from properties copy
            props.pop("raster:bands", None)

        if tmp_bands:
            # sanitize per-band tags: remove GDAL STATISTICS_* fields
            clean_bands = []
            for b in tmp_bands:
                b2 = dict(b)
                # remove STATISTICS_* entries
                if isinstance(b2.get("tags"), dict):
                    b2["tags"] = {k: v for k, v in b2.get("tags", {}).items() if not k.upper().startswith("STATISTICS_")}
                    if not b2["tags"]:
                        b2.pop("tags", None)
                else:
                    b2.pop("tags", None)
                # normalize band unit: treat '-' as empty
                if b2.get("unit") == "-":
                    b2.pop("unit", None)
                # ensure band unit matches normalized trait unit when applicable
                if props.get("trait_unit") and not b2.get("unit"):
                    b2["unit"] = props.get("trait_unit")
                clean_bands.append(b2)

            assets = item_json.get("assets", {})
            data_asset = assets.get("data") or {}
            # place raster:bands under the asset dict per Raster extension
            data_asset["raster:bands"] = clean_bands
            assets["data"] = data_asset
            item_json["assets"] = assets

        # Ensure proj:transform is present when raster metadata provided a numeric transform
        try:
            # if the item json came from an existing file it may contain a top-level
            # 'transform' in properties or dataset_tags; prefer proj:transform and
            # remove other copies
            if (not item_json.get("properties", {}).get("proj:transform")):
                # try raw_props first, then props, then attempt to read asset href
                src_tr = None
                # raw_props may include a 'transform' key from older dumps
                if isinstance(raw_props.get("transform"), list):
                    src_tr = raw_props.get("transform")
                elif isinstance(props.get("transform"), list):
                    src_tr = props.get("transform")
                if src_tr and isinstance(src_tr, (list, tuple)):
                    try:
                        item_json.setdefault("properties", {})
                        item_json["properties"]["proj:transform"] = [float(x) for x in list(src_tr)[:6]]
                        # remove other transform copies
                        item_json["properties"].pop("transform", None)
                    except Exception:
                        pass
        except Exception:
            pass

        # Ensure asset media type and roles are present
        if "assets" in item_json and "data" in item_json["assets"]:
            a = item_json["assets"]["data"]
            a.setdefault("type", COG_MEDIA_TYPE)
            if not isinstance(a.get("roles"), list):
                a["roles"] = ["data"]

        # desired links for item (relative to items/ directory)
        if ROOT_HREF.startswith("./"):
            root_rel = "../" + ROOT_HREF.lstrip("./")
        else:
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
            # Always write sanitized JSON. When preserving items we still want
            # to remove sensitive or redundant metadata (license, embedded
            # TIFF tags, etc.). This updates metadata without changing asset
            # hrefs or IDs.
            item_path.write_text(_json.dumps(item_json, indent=2), encoding="utf-8")
        except Exception as exc:  # pragma: no cover - IO/runtime environment errors
            raise RuntimeError(f"Failed to write item {item.id} to {item_path}: {exc}")

        # add collection -> item link (relative path)
        collection_item_links.append({"rel": "item", "href": f"./items/{item.id}.json", "type": "application/geo+json"})

    # Instead of relying on the collected links (which were built from the
    # set of items_to_write), regenerate the collection's item links from the
    # actual files present in the items directory. This ensures all written
    # item files are referenced in collection.json and avoids omissions when
    # extending the collection across multiple runs.
    # Clear any existing item links
    collection.links = [l for l in (collection.links or []) if l.rel != "item"]
    # Find all item files and add an item link for each
    for p in sorted(items_dir.glob("*.json")):
        collection.add_link(pystac.Link("item", f"./items/{p.name}", media_type="application/geo+json"))

    # Sanitize all item files in items_dir to remove legacy/raw TIFF metadata
    # and ensure raster:bands live under assets.data. This guarantees a
    # consistent, non-redundant layout even for items that were not part of
    # the current run (preserve-existing-items mode).
    for p in sorted(items_dir.glob("*.json")):
        try:
            jd = _json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue

        raw_props = jd.get("properties", {}) or {}
        props = {k: v for k, v in raw_props.items() if k not in ("datetime", "start_datetime", "end_datetime")}
        # remove temporary fields
        props.pop("_raster_bands_tmp", None)

        # normalize trait_unit
        if props.get("trait_unit"):
            props["trait_unit"] = _normalize_trait_unit(props.get("trait_unit"), props.get("trait_long_name"))

        # remove internal/conflicting fields
        for internal in ("stat_id", "stat_name", "license", "rights"):
            props.pop(internal, None)
        for dup in ("nodata", "dtype", "resolution", "width", "height", "transform", "bbox", "crs"):
            props.pop(dup, None)
        # drop any affine/transform/resolution-like strings tucked into properties
        for tkey in ("transform", "affine", "resolution", "spatial_extent"):
            props.pop(tkey, None)

        # parse and normalize dataset_tags from any raw compact tags
        dt_raw = props.get("dataset_tags") or raw_props.get("dataset_tags") or {}
        if isinstance(dt_raw, dict):
            for tk in ("transform", "affine", "resolution", "crs", "width", "height", "spatial_extent"):
                dt_raw.pop(tk, None)
        parsed = _parse_dataset_tags(dt_raw)
        if parsed:
            # Remove provenance/contact keys so collection-level metadata is authoritative
            for rm in ("author", "contact", "organization"):
                parsed.pop(rm, None)
            props["dataset_tags"] = parsed
        else:
            props.pop("dataset_tags", None)

        jd["properties"] = props

        # move raster bands if present in properties into asset and clean them
        tmp_bands = None
        if isinstance(raw_props.get("_raster_bands_tmp"), list):
            tmp_bands = raw_props.get("_raster_bands_tmp")
        elif isinstance(props.get("raster:bands"), list):
            tmp_bands = props.get("raster:bands")
            props.pop("raster:bands", None)

        if tmp_bands:
            clean_bands = []
            for b in tmp_bands:
                b2 = dict(b)
                # drop STATISTICS_* entries from tags
                if isinstance(b2.get("tags"), dict):
                    b2["tags"] = {k: v for k, v in b2.get("tags", {}).items() if not k.upper().startswith("STATISTICS_")}
                    if not b2["tags"]:
                        b2.pop("tags", None)
                else:
                    b2.pop("tags", None)
                # ensure band unit matches trait unit when applicable
                if props.get("trait_unit") and not b2.get("unit"):
                    b2["unit"] = props.get("trait_unit")
                clean_bands.append(b2)

            assets = jd.get("assets", {})
            data_asset = assets.get("data") or {}
            data_asset["raster:bands"] = clean_bands
            assets["data"] = data_asset
            jd["assets"] = assets

        # ensure asset media type and roles
        if "assets" in jd and "data" in jd["assets"]:
            a = jd["assets"]["data"]
            a.setdefault("type", COG_MEDIA_TYPE)
            if not isinstance(a.get("roles"), list):
                a["roles"] = ["data"]

        # preserve acronyms in description
        try:
            if isinstance(jd.get("properties", {}).get("description"), str):
                jd["properties"]["description"] = _preserve_acronyms(jd["properties"]["description"])
        except Exception:
            pass

        # ensure proj:transform exists and drop old transform-like copies
        try:
            jprops = jd.get("properties", {}) or {}
            # if proj:transform missing, look for a numeric 'transform' in props
            if not jprops.get("proj:transform"):
                cand = None
                if isinstance(raw_props.get("transform"), list):
                    cand = raw_props.get("transform")
                elif isinstance(jprops.get("transform"), list):
                    cand = jprops.get("transform")
                if cand and isinstance(cand, (list, tuple)):
                    try:
                        jprops["proj:transform"] = [float(x) for x in list(cand)[:6]]
                    except Exception:
                        pass
            # remove other copies
            jprops.pop("transform", None)
            jprops.pop("affine", None)
            jprops.pop("resolution", None)
            jd["properties"] = jprops
        except Exception:
            pass
        # write back sanitized JSON
        try:
            p.write_text(_json.dumps(jd, indent=2), encoding="utf-8")
        except Exception:
            # non-fatal; continue sanitizing other files
            continue

    # Final sweep: ensure assets.data.raster:bands have no empty tags and
    # that band units are consistent with item trait_unit
    for p in sorted(items_dir.glob("*.json")):
        try:
            jd = _json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        props = jd.get("properties", {}) or {}
        trait_unit = props.get("trait_unit")
        assets = jd.get("assets", {})
        data = assets.get("data") or {}
        bands = data.get("raster:bands")
        changed = False
        if isinstance(bands, list):
            for b in bands:
                # remove empty tags dicts
                if isinstance(b.get("tags"), dict) and not b["tags"]:
                    b.pop("tags", None)
                    changed = True
                # normalize '-' unit
                if b.get("unit") == "-":
                    if trait_unit:
                        b["unit"] = trait_unit
                    else:
                        b.pop("unit", None)
                    changed = True
            if changed:
                data["raster:bands"] = bands
                assets["data"] = data
                jd["assets"] = assets
                try:
                    p.write_text(_json.dumps(jd, indent=2), encoding="utf-8")
                except Exception:
                    pass

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
