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

from .config import get_collection_config, COG_MEDIA_TYPE, ASSET_BASE_HREF, ZENODO_FILE_BASE_URL

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
    # We prefer to keep `datetime` as None (no single instant), but pystac
    # requires either `datetime` or a start/end interval. Provide a stable
    # start/end placeholder while leaving `datetime` set to None so the
    # resulting JSON will contain start_datetime/end_datetime but no
    # properties-stored datetime.
    start_end_placeholder = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)

    # Only include bbox when we have a valid WGS84 geometry (to avoid
    # including projected coordinates in top-level bbox). If geometry is
    # present, set bbox to the WGS84 bbox; otherwise leave bbox None.
    item_bbox = wgs_bbox if geometry is not None else None

    item = pystac.Item(
        id=item_id,
        geometry=geometry,
        bbox=item_bbox,
        datetime=None,
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
    asset = pystac.Asset(href=href, media_type=media_type, roles=["data"])
    item.add_asset("data", asset)

    # store projected/native spatial metadata in properties using extension-
    # friendly keys so we don't expose projected coordinates in STAC core.
    # Keep keys simple and easy to map to proj extension later.
    native_bbox = rast_meta.get("native_bbox")
    if rast_meta.get("crs") is not None:
        # prefer an EPSG int if present
        properties.setdefault("proj:crs", rast_meta.get("crs"))
    if native_bbox:
        properties.setdefault("proj:bbox", native_bbox)
    # update properties on the item
    item.properties.update(properties)

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


# OSC (Open Science Catalog) helper constants and applicator
# NOTE: use a placeholder extension URL here; replace with the official OSC
# extension schema URL when available/decided.
OSC_EXTENSION = "https://example.org/extensions/osc.json"  # TODO: replace with official OSC extension URL


def apply_osc_collection_fields(collection: pystac.Collection) -> pystac.Collection:
        """Apply minimal OSC-compatible placeholder fields to a Collection.

        This function mutates and returns the given collection. It adds a small
        set of `extra_fields` that the ESA OSC expects (placeholder values), and
        registers an OSC extension in `stac_extensions` so it's easy to find and
        replace later with authoritative metadata.

        TODO:
            - replace placeholder values for `osc:project`, `osc:theme` with real
                project metadata coming from Zenodo or a metadata file
            - consider mirroring some collection-level OSC fields to items later
                (e.g. project or theme)
        """
        # Ensure extra_fields exists and is a dict
        ef = collection.extra_fields or {}

        # Minimal OSC placeholders
        ef.setdefault("osc:type", "dataset")
        ef.setdefault("osc:status", "draft")
        ef.setdefault("osc:project", {
                "id": "esa-trait-maps",
                "title": "ESA trait maps scaffold",
                "description": "Placeholder project information — replace with real project metadata",
        })

        # attach back
        collection.extra_fields = ef

        # register the OSC extension in stac_extensions for discoverability
        stac_exts = list(collection.stac_extensions or [])
        if OSC_EXTENSION not in stac_exts:
                stac_exts.append(OSC_EXTENSION)
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

    # add placeholder links (use Link constructor for broad pystac compatibility)
    # Do not add a 'root' link pointing to project root; it may not resolve
    # to a STAC object when catalogs are normalized. Add only self and
    # describedby links.
    coll.add_link(pystac.Link("self", "./collection.json"))
    coll.add_link(pystac.Link("describedby", cfg.get("zenodo_doi_url"), media_type="text/html"))

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


def save_collection(collection: pystac.Collection, output_dir: Path) -> None:
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

    # Ensure collection self href is the collection.json path
    collection_path = output_dir / "collection.json"
    collection.set_self_href(str(collection_path))

    # Save each item into the items/ directory with flat layout and explicit links
    for item in collection.get_items():
        # remove temporal keys from properties if present (they belong top-level)
        for tf in ("start_datetime", "end_datetime", "datetime", "end_datetime"):
            if tf in (item.properties or {}):
                item.properties.pop(tf, None)

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

        # prepare item href and links (relative links: items are in ./items/)
        item_path = items_dir / f"{item.id}.json"

        # set self href to absolute path so save_object writes to correct file
        item.set_self_href(str(item_path))

        # ensure collection/parent/root links point to ../collection.json (relative from items/)
        rel_coll = "../collection.json"
        item.add_link(pystac.Link("self", f"./items/{item.id}.json"))
        item.add_link(pystac.Link("collection", rel_coll))
        item.add_link(pystac.Link("root", rel_coll))
        item.add_link(pystac.Link("parent", rel_coll))

        # finally write the item JSON
        item.save_object()

    # Save collection JSON (collection links already set earlier)
    collection.save_object()
