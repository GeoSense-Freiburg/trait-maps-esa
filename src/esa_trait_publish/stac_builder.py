"""Build STAC Collections and Items for global plant trait maps.

"""

from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional
import datetime
import json as _json
import logging
import re

import pystac

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
    PUBLISHED_DATE_END,
    KEYWORDS,
    PROVIDERS,
    OSC_MISSIONS,
    PUBLICATION_DOI,
    DOCUMENTATION_URL,
)

from .filename_parser import parse_filename
from .raster_metadata import extract_raster_metadata
from .trait_metadata import (
    load_trait_metadata,
    load_stat_metadata,
    build_metadata_record,
)


LOGGER = logging.getLogger(__name__)

ACRONYMS = {"SRL", "SLA", "LMA", "LDMC", "CV"}
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

INTERNAL_ITEM_PROPERTIES = {
    "_raster_bands_tmp",
    "stat_id",
    "stat_name",
    "license",
    "rights",
    "nodata",
    "dtype",
    "resolution",
    "width",
    "height",
    "transform",
    "bbox",
    "crs",
    "affine",
    "spatial_extent",
    "start_datetime",
    "end_datetime",
}

DATASET_TAG_DENYLIST = {
    "transform",
    "affine",
    "resolution",
    "crs",
    "width",
    "height",
    "spatial_extent",
    "author",
    "contact",
    "organization",
}

DATASET_TAG_ALLOWLIST = {
    "model_performance",
    "pfts",
    "source_creation_date",
    "usage_notes",
    "keywords",
}


def doi_to_url(doi: str) -> Optional[str]:
    """Normalize a DOI string to a full ``https://doi.org/...`` URL."""
    if not doi:
        return None

    value = str(doi).strip()
    lower = value.lower()

    if lower.startswith(("http://doi.org", "https://doi.org")):
        return value
    if lower.startswith("doi.org/"):
        return f"https://{value}"
    return f"https://doi.org/{value}"


def _parse_datetime(value: str) -> datetime.datetime:
    """Parse an ISO datetime string that may use a trailing ``Z``."""
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _json_write(path: Path, payload: dict) -> None:
    """Write JSON consistently."""
    path.write_text(_json.dumps(payload, indent=2), encoding="utf-8")


def _ensure_extension(stac_object: pystac.STACObject, extension_url: str) -> None:
    extensions = list(stac_object.stac_extensions or [])
    if extension_url not in extensions:
        extensions.append(extension_url)
    stac_object.stac_extensions = extensions


def _preserve_acronyms(text: str) -> str:
    if not text:
        return text

    output = text
    for acronym in ACRONYMS:
        output = re.sub(rf"\b{acronym.lower()}\b", acronym, output, flags=re.IGNORECASE)
    return output


def _restore_acronyms_in_text(text: str) -> str:
    """Replace known acronym tokens without changing sentence case."""
    if not text:
        return text

    output = text
    for token, replacement in ACRONYM_MAP.items():
        output = re.sub(rf"\b{re.escape(token)}\b", replacement, output, flags=re.IGNORECASE)
    return output


def _format_stat_label(stat_name: Optional[str]) -> str:
    if not stat_name:
        return ""

    mapping = {
        "mean": "Mean",
        "median": "Median",
        "cv": "Coefficient of Variation",
    }
    value = str(stat_name).strip().lower()
    return mapping.get(value, value.title())


def _normalize_trait_unit(trait_unit: Optional[str], trait_long_name: Optional[str]) -> str:
    """Normalize empty placeholder trait units."""
    unit = str(trait_unit or "").strip()

    if unit and unit != "-":
        return unit

    trait_name = (trait_long_name or "").lower()
    if any(token in trait_name for token in ("number", "count", "density", "per ", "per/", "per-")):
        return "count"
    return "unitless"


def build_item_title(trait_long_name: Optional[str], stat_name: Optional[str]) -> str:
    trait = (trait_long_name or "Trait").strip()
    stat_label = _format_stat_label(stat_name)
    pieces = [trait, stat_label] if stat_label else [trait]
    return f"{_preserve_acronyms(' '.join(pieces))} — Global 1 km Plant Trait Map"


def build_item_title_short(trait_long_name: Optional[str], stat_name: Optional[str]) -> str:
    trait = (trait_long_name or "Trait").strip()
    stat_label = _format_stat_label(stat_name)
    pieces = [trait, stat_label] if stat_label else [trait]
    return _preserve_acronyms(" ".join(pieces))


def build_item_description(trait_long_name: Optional[str], stat_name: Optional[str]) -> str:
    trait = (trait_long_name or "trait").strip().lower()
    stat = (stat_name or "").strip().lower()

    if stat == "cv":
        stat_phrase = "coefficient of variation of"
    elif stat in {"mean", "median"}:
        stat_phrase = stat
    elif stat:
        stat_phrase = stat
    else:
        stat_phrase = "statistic"

    description = (
        f"Global 1 km map of community-weighted {stat_phrase} {trait} "
        "derived from GBIF, sPlot, TRY, and Earth observation predictors."
    )
    description = description[0].upper() + description[1:]
    return _preserve_acronyms(_restore_acronyms_in_text(description))


def infer_product_status_from_path(path: Path) -> str:
    """Infer product status from a path string."""
    allowed = {"analysis-ready", "experimental", "hydraulic"}
    path_text = str(path).lower()

    for token in allowed:
        if token in path_text:
            return token

    raise ValueError(f"Could not infer product status from path: {path}")


def build_asset_href(raster_path: Path, base: Optional[str] = None) -> str:
    """Return asset href built from a base URL and filename, or local path."""
    chosen_base = base or ZENODO_FILE_BASE_URL

    if not chosen_base and ASSET_BASE_HREF and ASSET_BASE_HREF != "REPLACE_WITH_ZENODO_FILE_BASE_URL":
        chosen_base = ASSET_BASE_HREF

    if chosen_base:
        return f"{chosen_base.rstrip('/')}/{raster_path.name}"

    return str(raster_path.resolve())


def build_item_assets() -> Dict[str, object]:
    """Return the canonical collection-level ``item_assets`` mapping."""
    return {
        "data": {
            "type": COG_MEDIA_TYPE,
            "roles": ["data"],
            "title": "Cloud-Optimized GeoTIFF trait raster",
        }
    }


def build_collection_summaries(items: Iterable[pystac.Item]) -> Dict[str, List[str]]:
    """Aggregate selected item properties into collection summaries."""
    fields = ["trait_short_name", "trait_unit", "stat_name", "proj:code", "trait_map:product_status"]
    values: Dict[str, List[str]] = {field: [] for field in fields}

    for item in items:
        props = item.properties or {}
        for field in fields:
            raw_value = props.get(field)
            if raw_value is None:
                continue

            candidates = raw_value if isinstance(raw_value, (list, tuple)) else [raw_value]
            for candidate in candidates:
                if candidate is None:
                    continue
                value = str(candidate).strip()
                if value and value not in values[field]:
                    values[field].append(value)

    return {
        field: sorted(field_values, key=lambda x: x.lower())
        for field, field_values in values.items()
        if field_values
    }


def _merge_summaries(existing: Dict[str, list], new: Dict[str, list]) -> Dict[str, list]:
    merged: Dict[str, list] = {}

    for key in sorted(set(existing) | set(new)):
        values = list(dict.fromkeys([*(existing.get(key) or []), *(new.get(key) or [])]))
        if values:
            merged[key] = sorted(values, key=lambda x: str(x).lower())

    return merged


def _parse_dataset_tags(raw: dict) -> Optional[dict]:
    """Parse raw TIFF dataset tags into compact item-level dataset tags."""
    if not raw or not isinstance(raw, dict):
        return None

    cleaned = {k: v for k, v in raw.items() if k not in DATASET_TAG_DENYLIST}
    output = {}

    keywords = cleaned.get("keywords") or cleaned.get("Keywords") or cleaned.get("KEYWORDS")
    if isinstance(keywords, str) and keywords.strip():
        output["keywords"] = [item.strip().lower() for item in keywords.split(",") if item.strip()]
    elif isinstance(keywords, list):
        output["keywords"] = keywords

    pfts = cleaned.get("PFTs") or cleaned.get("pfts") or cleaned.get("pft")
    if isinstance(pfts, str) and pfts.strip():
        output["pfts"] = pfts

    creation_date = cleaned.get("creation_date") or cleaned.get("creationDate") or cleaned.get("CreationDate")
    if isinstance(creation_date, str) and creation_date.strip():
        output["source_creation_date"] = creation_date

    model_performance = cleaned.get("model_performance") or cleaned.get("modelPerformance")
    if isinstance(model_performance, str) and model_performance.strip():
        try:
            output["model_performance"] = _json.loads(model_performance)
        except Exception:
            output["model_performance"] = model_performance
    elif isinstance(model_performance, dict):
        output["model_performance"] = model_performance

    usage_notes = cleaned.get("usage_notes") or cleaned.get("usageNotes") or cleaned.get("usage")
    if isinstance(usage_notes, str) and usage_notes.strip():
        output["usage_notes"] = usage_notes

    # Keep only explicitly allowed compact tags.
    output = {k: v for k, v in output.items() if k in DATASET_TAG_ALLOWLIST and v not in (None, "", [])}
    return output or None


def _band_name(band_index: Optional[int], description: Optional[str]) -> str:
    description_lower = (description or "").lower()

    if "coefficient of variation" in description_lower or " cv" in description_lower:
        return "coefficient_of_variation"
    if "area of applicability" in description_lower:
        return "area_of_applicability"
    if "mean" in description_lower or "(mean)" in (description or ""):
        return "trait_mean"
    return f"band_{band_index}"


def _band_unit(band: dict, record: dict) -> str:
    unit = band.get("unit")
    if unit:
        return unit

    band_index = band.get("band_index")
    if band_index == 1:
        return record.get("trait_unit") or "unitless"
    if band_index == 2:
        return "%"
    if band_index == 3:
        return "binary mask"
    return "unitless"


def _build_raster_bands(rast_meta: dict, record: dict) -> list:
    bands = []

    for band in rast_meta.get("bands", []) or []:
        entry = {
            "name": _band_name(band.get("band_index"), band.get("description")),
            "description": band.get("description"),
            "data_type": band.get("dtype"),
            "nodata": band.get("nodata"),
            "unit": _band_unit(band, record),
            "sampling": "area",
        }

        for key in ("scale", "offset", "overviews"):
            if band.get(key) is not None:
                entry[key] = band.get(key)

        tags = band.get("tags")
        if isinstance(tags, dict):
            tags = {k: v for k, v in tags.items() if not k.upper().startswith("STATISTICS_")}
            if tags:
                entry["tags"] = tags

        bands.append({k: v for k, v in entry.items() if v is not None})

    return bands


def _add_projection_properties(item: pystac.Item, rast_meta: dict) -> None:
    if rast_meta.get("crs") is not None:
        try:
            item.properties.setdefault("proj:code", f"EPSG:{int(rast_meta.get('crs'))}")
        except Exception:
            item.properties.setdefault("proj:code", str(rast_meta.get("crs")))

    if rast_meta.get("native_bbox"):
        item.properties.setdefault("proj:bbox", rast_meta.get("native_bbox"))

    transform = rast_meta.get("transform")
    if isinstance(transform, (list, tuple)):
        try:
            item.properties.setdefault("proj:transform", [float(x) for x in list(transform)[:6]])
        except Exception:
            pass

    if rast_meta.get("width") and rast_meta.get("height"):
        item.properties.setdefault("proj:shape", [rast_meta.get("height"), rast_meta.get("width")])

    resolution = rast_meta.get("resolution")
    if resolution and isinstance(resolution, (list, tuple)) and resolution[0]:
        try:
            item.properties.setdefault("gsd", int(round(abs(resolution[0]))))
        except Exception:
            pass


def _add_dataset_tags(item: pystac.Item, rast_meta: dict) -> None:
    raw_tags = rast_meta.get("compact_tags") or rast_meta.get("tags") or {}
    dataset_tags = _parse_dataset_tags(raw_tags)

    if dataset_tags:
        item.properties.setdefault("dataset_tags", dataset_tags)


def apply_osc_collection_fields(collection: pystac.Collection) -> pystac.Collection:
    """Apply OSC extension and required OSC collection fields."""
    extra_fields = collection.extra_fields or {}
    extra_fields.update(
        {
            "osc:type": OSC_TYPE,
            "osc:status": OSC_STATUS,
            "osc:project": OSC_PROJECT,
        }
    )
    collection.extra_fields = extra_fields
    _ensure_extension(collection, OSC_EXTENSION)
    return collection


def _collection_reference_links() -> List[pystac.Link]:
    """Return authoritative non-navigation collection links."""
    return [
        pystac.Link("self", "./collection.json", media_type="application/json"),
        pystac.Link(
            "describedby",
            PUBLICATION_DOI,
            media_type="text/html",
            title="Associated Publication",
        ),
        pystac.Link(
            "cite-as",
            doi_to_url(DOI_URL) or DOI_URL,
            media_type="text/html",
            title="Dataset DOI",
        ),
        pystac.Link(
            "via",
            DOCUMENTATION_URL,
            media_type="text/html",
            title="Dataset Documentation",
        ),
    ]


def create_collection() -> pystac.Collection:
    """Create the authoritative base STAC Collection."""
    cfg = get_collection_config()

    spatial = pystac.SpatialExtent([cfg.get("spatial_extent")])
    temporal = pystac.TemporalExtent(
        [[_parse_datetime(PUBLISHED_DATE), _parse_datetime(PUBLISHED_DATE_END)]]
    )
    extent = pystac.Extent(spatial=spatial, temporal=temporal)

    collection = pystac.Collection(
        id=cfg.get("id"),
        description=cfg.get("description"),
        extent=extent,
        title=cfg.get("title"),
        license=cfg.get("license"),
    )

    apply_osc_collection_fields(collection)
    _ensure_extension(collection, SCIENTIFIC_EXTENSION)

    collection.keywords = list(KEYWORDS)
    collection.providers = [
        pystac.Provider(name=provider.get("name"), roles=provider.get("roles"))
        for provider in PROVIDERS
    ]

    collection.extra_fields = {
        **(collection.extra_fields or {}),
        "osc:missions": list(OSC_MISSIONS),
        "sci:doi": DOI,
        "sci:citation": SCIENTIFIC_CITATION,
        "published": PUBLISHED_DATE,
        "trait_map:contacts": [
            {
                "name": "Daniel Lusk",
                "role": "creator",
                "email": "daniel.lusk@geosense.uni-freiburg.de",
                "organization": "Chair of Sensor-based Geoinformatics, University of Freiburg",
            }
        ],
    }

    collection.links = []
    for link in _collection_reference_links():
        collection.add_link(link)

    return collection


def create_item_from_raster(
    raster_path: Path,
    trait_mapping: Dict,
    stat_mapping: Dict,
    base_asset_href: Optional[str] = None,
    asset_href_resolver: Optional[Callable[[Path], str]] = None,
) -> pystac.Item:
    """Create a STAC Item for a single raster file."""
    raster_path = Path(raster_path)

    parsed = parse_filename(raster_path)
    rast_meta = extract_raster_metadata(raster_path)
    record = build_metadata_record(parsed, trait_mapping, stat_mapping)

    trait_unit = _normalize_trait_unit(record.get("trait_unit"), record.get("trait_long_name"))
    properties = {
        "datetime": PUBLISHED_DATE,
        "trait_id": record.get("trait_id"),
        "trait_short_name": record.get("trait_short_name"),
        "trait_long_name": record.get("trait_long_name"),
        "trait_unit": trait_unit,
        "title": build_item_title(record.get("trait_long_name"), record.get("stat_name")),
        "description": build_item_description(record.get("trait_long_name"), record.get("stat_name")),
    }

    geometry = rast_meta.get("geometry")
    item_bbox = rast_meta.get("bbox") if geometry is not None else None

    # PySTAC requires start/end when datetime=None. These are removed at JSON
    # serialization so the public item keeps properties.datetime only.
    placeholder_datetime = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)

    item = pystac.Item(
        id=parsed.get("stem") or raster_path.stem,
        geometry=geometry,
        bbox=item_bbox,
        datetime=None,
        start_datetime=placeholder_datetime,
        end_datetime=placeholder_datetime,
        properties=properties,
    )

    href = asset_href_resolver(raster_path) if asset_href_resolver else build_asset_href(raster_path, base_asset_href)
    asset_title = f"{build_item_title_short(record.get('trait_long_name'), record.get('stat_name'))} Raster"
    item.add_asset("data", pystac.Asset(href=href, media_type=COG_MEDIA_TYPE, roles=["data"], title=asset_title))

    if "data" not in (item.assets or {}):
        raise RuntimeError(f"Item {item.id} missing required 'data' asset (href={href})")

    _add_projection_properties(item, rast_meta)
    _add_dataset_tags(item, rast_meta)

    raster_bands = _build_raster_bands(rast_meta, record)
    if raster_bands:
        item.properties["_raster_bands_tmp"] = raster_bands

    _ensure_extension(item, PROJECTION_EXTENSION)
    _ensure_extension(item, RASTER_EXTENSION)

    return item


def _is_valid_raster_file(path: Path) -> bool:
    name = path.name

    if name.startswith(("._", ".")) or not path.is_file():
        return False

    return name.lower().endswith((".tif", ".tiff"))


def _iter_raster_files(maps_dir: Path) -> List[Path]:
    files = []

    for path in Path(maps_dir).iterdir():
        if _is_valid_raster_file(path):
            files.append(path)
        else:
            LOGGER.debug("Skipping non-raster or sidecar file: %s", path.name)

    return sorted(files, key=lambda path: path.name.lower())


def build_collection_from_directory(
    maps_dir: Path,
    trait_metadata_path: Path,
    stat_metadata_path: Path,
    base_asset_href: Optional[str] = None,
    asset_href_resolver: Optional[Callable[[Path], str]] = None,
) -> pystac.Collection:
    """Build a collection populated from rasters in ``maps_dir``."""
    trait_map = load_trait_metadata(Path(trait_metadata_path))
    stat_map = load_stat_metadata(Path(stat_metadata_path))

    collection = create_collection()

    for raster_path in _iter_raster_files(Path(maps_dir)):
        item = create_item_from_raster(
            raster_path,
            trait_map,
            stat_map,
            base_asset_href=base_asset_href,
            asset_href_resolver=asset_href_resolver,
        )
        collection.add_item(item)

    return collection


def load_existing_collection(output_dir: Path) -> Optional[tuple[pystac.Collection, set]]:
    """Load an existing collection and parse existing item IDs from item links."""
    collection_path = Path(output_dir) / "collection.json"

    if not collection_path.exists():
        return None

    try:
        raw = _json.loads(collection_path.read_text(encoding="utf-8"))
        item_ids = {
            Path(link["href"]).stem
            for link in raw.get("links", []) or []
            if link.get("rel") == "item" and link.get("href")
        }
        collection = pystac.Collection.from_file(str(collection_path))
        return collection, item_ids
    except Exception:
        return None


def merge_items_into_collection(
    collection: pystac.Collection,
    new_items: List[pystac.Item],
    preserve_existing: bool = True,
    status: Optional[str] = None,
    existing_ids: Optional[set] = None,
) -> pystac.Collection:
    """Merge new items into a collection while avoiding ID collisions."""
    if existing_ids is None:
        try:
            existing_ids = {item.id for item in collection.get_items()}
        except Exception:
            existing_ids = set()

    added = 0

    for item in new_items:
        item_id = item.id

        if item_id in existing_ids:
            if preserve_existing:
                print(f"Skipping existing item: {item_id}")
                continue

            if status:
                alternative_id = f"{item_id}_{status}"
                if alternative_id in existing_ids:
                    print(f"Skipping item; both {item_id} and {alternative_id} exist")
                    continue

                print(f"ID conflict for {item_id}; adding as {alternative_id}")
                item.id = alternative_id
                item_id = alternative_id
            else:
                print(f"Skipping existing item: {item_id}")
                continue

        collection.add_item(item)
        existing_ids.add(item_id)
        added += 1

    print(f"Added {added} new items to collection {collection.id}")
    return collection


def _clean_raster_bands(bands: Optional[list], trait_unit: Optional[str]) -> Optional[list]:
    if not isinstance(bands, list):
        return None

    cleaned = []

    for band in bands:
        if not isinstance(band, dict):
            continue

        entry = dict(band)

        tags = entry.get("tags")
        if isinstance(tags, dict):
            tags = {k: v for k, v in tags.items() if not k.upper().startswith("STATISTICS_")}
            if tags:
                entry["tags"] = tags
            else:
                entry.pop("tags", None)
        else:
            entry.pop("tags", None)

        if entry.get("unit") == "-":
            if trait_unit:
                entry["unit"] = trait_unit
            else:
                entry.pop("unit", None)

        if trait_unit and not entry.get("unit"):
            entry["unit"] = trait_unit

        cleaned.append(entry)

    return cleaned or None


def _extract_raster_bands_from_properties(raw_props: dict) -> Optional[list]:
    if isinstance(raw_props.get("_raster_bands_tmp"), list):
        return raw_props.get("_raster_bands_tmp")
    if isinstance(raw_props.get("raster:bands"), list):
        return raw_props.get("raster:bands")
    return None


def _sanitize_item_json(item_json: dict, collection_title: Optional[str]) -> dict:
    """Return a clean serialized STAC Item JSON dictionary."""
    raw_props = item_json.get("properties", {}) or {}
    props = dict(raw_props)

    for key in INTERNAL_ITEM_PROPERTIES:
        props.pop(key, None)

    props["datetime"] = props.get("datetime") or PUBLISHED_DATE

    if props.get("trait_unit"):
        props["trait_unit"] = _normalize_trait_unit(props.get("trait_unit"), props.get("trait_long_name"))

    dataset_tags = _parse_dataset_tags(props.get("dataset_tags") or raw_props.get("dataset_tags") or {})
    if dataset_tags:
        props["dataset_tags"] = dataset_tags
    else:
        props.pop("dataset_tags", None)

    trait_long = props.get("trait_long_name") or props.get("trait_short_name") or ""
    stat_name = props.get("stat_name") or ""
    props["title"] = _preserve_acronyms(build_item_title(trait_long, stat_name))
    props["description"] = _preserve_acronyms(build_item_description(trait_long, stat_name))

    # Try to recover proj:transform from legacy transform fields before dropping
    # old keys completely.
    if not props.get("proj:transform"):
        transform = raw_props.get("transform")
        if isinstance(transform, (list, tuple)):
            try:
                props["proj:transform"] = [float(x) for x in list(transform)[:6]]
            except Exception:
                pass

    item_json["properties"] = props

    item_json.pop("datetime", None)
    item_json.pop("start_datetime", None)
    item_json.pop("end_datetime", None)

    assets = item_json.get("assets") or {}
    data_asset = assets.get("data") or {}
    data_asset.setdefault("type", COG_MEDIA_TYPE)
    if not isinstance(data_asset.get("roles"), list):
        data_asset["roles"] = ["data"]

    raster_bands = _clean_raster_bands(_extract_raster_bands_from_properties(raw_props), props.get("trait_unit"))
    if raster_bands:
        data_asset["raster:bands"] = raster_bands

    assets["data"] = data_asset
    item_json["assets"] = assets

    item_json["links"] = [
        {
            "rel": "root",
            "href": "../catalog.json",
            "type": "application/json",
            "title": "Global Plant Functional Trait Maps STAC Catalog",
        },
        {
            "rel": "parent",
            "href": "../collection.json",
            "type": "application/json",
            "title": collection_title,
        },
        {
            "rel": "collection",
            "href": "../collection.json",
            "type": "application/json",
            "title": collection_title,
        },
        {
            "rel": "self",
            "href": f"./{item_json.get('id')}.json",
            "type": "application/geo+json",
        },
    ]

    return item_json


def _serialize_item(item: pystac.Item, item_path: Path, overwrite_items: bool, collection_title: Optional[str]) -> dict:
    """Serialize one item, merging selected generated fields into existing JSON when requested."""
    item_json = item.to_dict()

    if item_path.exists() and not overwrite_items:
        try:
            existing = _json.loads(item_path.read_text(encoding="utf-8"))
            existing_props = existing.get("properties", {}) or {}
            generated_props = item.properties or {}

            for key in (
                "proj:transform",
                "proj:code",
                "proj:bbox",
                "proj:shape",
                "gsd",
                "trait_unit",
                "title",
                "description",
                "datetime",
                "_raster_bands_tmp",
            ):
                if key not in existing_props and generated_props.get(key) is not None:
                    existing_props[key] = generated_props[key]

            existing["properties"] = existing_props
            existing.setdefault("assets", item_json.get("assets", {}))
            item_json = existing
        except Exception:
            item_json = item.to_dict()

    return _sanitize_item_json(item_json, collection_title)


def _all_item_paths(items_dir: Path) -> List[Path]:
    return sorted(items_dir.glob("*.json"), key=lambda path: path.name.lower())


def _refresh_collection_links(collection: pystac.Collection, items_dir: Path) -> None:
    """Keep collection metadata links and regenerate item links from files."""
    preserved = [
        link
        for link in (collection.links or [])
        if link.rel not in {"root", "parent", "item"}
    ]

    collection.links = preserved

    for item_path in _all_item_paths(items_dir):
        collection.add_link(
            pystac.Link(
                "item",
                f"./items/{item_path.name}",
                media_type="application/geo+json",
            )
        )


def _sanitize_collection_json(collection_json: dict) -> dict:
    """Return collection JSON with canonical navigation links and preserved metadata links."""
    root_link = {
        "rel": "root",
        "href": "./catalog.json",
        "type": "application/json",
        "title": "Global Plant Functional Trait Maps STAC Catalog",
    }
    parent_link = {
        "rel": "parent",
        "href": "./catalog.json",
        "type": "application/json",
        "title": "Global Plant Functional Trait Maps STAC Catalog",
    }
    self_link = {"rel": "self", "href": "./collection.json", "type": "application/json"}

    sanitized = [root_link, parent_link]
    seen = {("root", "./catalog.json"), ("parent", "./catalog.json")}

    def add_once(link: dict) -> None:
        key = (link.get("rel"), link.get("href"))
        if key not in seen:
            sanitized.append(link)
            seen.add(key)

    add_once(self_link)

    for link in collection_json.get("links", []) or []:
        rel = link.get("rel")

        if rel in {"root", "parent", "self"}:
            continue

        # Keep collection-level metadata links as created by create_collection().
        # Do not reinterpret describedby/cite-as/via here.
        add_once(link)

    collection_json["links"] = sanitized
    return collection_json


def _write_catalog(output_dir: Path, collection: pystac.Collection) -> None:
    try:
        from .config import CATALOG_ID, PRODUCT_TITLE

        catalog = {
            "type": "Catalog",
            "id": CATALOG_ID,
            "stac_version": "1.1.0",
            "description": "Full STAC catalog for global plant functional trait maps at 1 km resolution.",
            "title": PRODUCT_TITLE,
            "links": [
                {"rel": "self", "href": "./catalog.json", "type": "application/json"},
                {"rel": "root", "href": "./catalog.json", "type": "application/json"},
                {
                    "rel": "child",
                    "href": "./collection.json",
                    "type": "application/json",
                    "title": collection.title,
                },
            ],
        }
        _json_write(output_dir / "catalog.json", catalog)
    except Exception:
        LOGGER.exception("Could not write top-level catalog.json")


def save_collection(
    collection: pystac.Collection,
    output_dir: Path,
    overwrite_items: bool = True,
    additional_items: Optional[List[pystac.Item]] = None,
    full_stac_catalog_url: Optional[str] = None,
) -> int:
    """Save collection and items as a flat static STAC catalog.

    ``full_stac_catalog_url`` is retained for backward-compatible function
    signature only; EarthCODE registry writing is no longer handled here.
    """
    del full_stac_catalog_url

    output_dir = Path(output_dir)
    items_dir = output_dir / "items"
    output_dir.mkdir(parents=True, exist_ok=True)
    items_dir.mkdir(parents=True, exist_ok=True)

    items_to_write = list(additional_items) if additional_items is not None else list(collection.get_items())
    collection_title = get_collection_config().get("title")

    new_summaries = build_collection_summaries(items_to_write)
    try:
        existing_summaries = collection.summaries.to_dict() if getattr(collection, "summaries", None) else {}
    except Exception:
        existing_summaries = {}

    merged_summaries = _merge_summaries(existing_summaries, new_summaries)
    if merged_summaries:
        collection.summaries = pystac.Summaries(merged_summaries)

    collection.extra_fields = {
        **(collection.extra_fields or {}),
        "item_assets": build_item_assets(),
    }

    for item in items_to_write:
        item_path = items_dir / f"{item.id}.json"
        item_json = _serialize_item(item, item_path, overwrite_items, collection_title)
        _json_write(item_path, item_json)

    _refresh_collection_links(collection, items_dir)

    collection_json = _sanitize_collection_json(collection.to_dict())
    _json_write(output_dir / "collection.json", collection_json)

    _write_catalog(output_dir, collection)

    return len(items_to_write)
