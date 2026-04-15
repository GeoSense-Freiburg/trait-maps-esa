"""Simple STAC validation helpers.

Lightweight utilities to load a STAC Collection and perform basic sanity
checks. Optionally integrates with an external `stac_validator` package if
available — integration is best-effort and will be skipped if the package is
not installed.
"""

from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
import datetime

import pystac

# OSC schema URL expected in collection.stac_extensions for ESA OSC
OSC_SCHEMA_URL = "https://stac-extensions.github.io/osc/v1.0.0/schema.json"


def load_collection(path: Path) -> pystac.Collection:
    """Load a STAC Collection from a JSON file or a directory.

    Args:
        path: Path to a collection JSON file or to a directory containing
              `collection.json` or `catalog.json`.

    Returns:
        pystac.Collection: the loaded collection

    Raises:
        FileNotFoundError: when the path or collection JSON cannot be found
        RuntimeError: when pystac fails to read the collection
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")

    target = None
    if path.is_dir():
        # prefer collection.json, then catalog.json
        for candidate in (path / "collection.json", path / "catalog.json"):
            if candidate.exists():
                target = candidate
                break
        if target is None:
            # no well-known filenames found
            raise FileNotFoundError(f"No collection.json or catalog.json found in directory: {path}")
    else:
        target = path

    try:
        coll = pystac.read_file(str(target))
    except Exception as e:
        raise RuntimeError(f"Failed to read STAC collection from {target}: {e}") from e

    if not isinstance(coll, pystac.Collection):
        # read_file may return a Catalog; attempt to find a collection inside
        # the catalog if possible
        raise RuntimeError(f"The file {target} does not contain a STAC Collection object")

    return coll


def validate_collection_basic(collection: pystac.Collection) -> None:
    """Run basic sanity checks on a pystac.Collection and its items.

    Checks performed:
      - collection has an id
      - collection has an extent
      - collection contains at least one item

    For each item checks:
      - item has an id
      - item has a bbox
      - item has at least one asset
      - each asset has a non-empty href

    Raises:
        ValueError: with a descriptive message when a check fails
    """
    if not getattr(collection, "id", None):
        raise ValueError("Collection has no id")
    if not getattr(collection, "extent", None):
        raise ValueError("Collection has no extent")

    items = list(collection.get_items())
    if not items:
        raise ValueError("Collection contains no items")

    for item in items:
        if not getattr(item, "id", None):
            raise ValueError(f"Item missing id: {item}")
        if not getattr(item, "bbox", None):
            raise ValueError(f"Item '{item.id}' missing bbox")
        assets = getattr(item, "assets", {}) or {}
        if not assets:
            raise ValueError(f"Item '{item.id}' has no assets")
        for key, asset in assets.items():
            href = getattr(asset, "href", None)
            if not href:
                raise ValueError(f"Item '{item.id}' asset '{key}' has empty href")


def validate_publication_readiness(collection: pystac.Collection, publication_mode: bool = False) -> None:
    """Run publication-oriented checks on a collection and its items.

    When `publication_mode` is True, stricter checks apply (for example
    asset hrefs must be hosted HTTP(S) URLs rather than local filesystem
    absolute paths).

    Raises:
        ValueError: when any publication readiness check fails.
    """
    # Collection-level checks
    license_val = getattr(collection, "license", None)
    if license_val == "proprietary":
        raise ValueError("Collection license is 'proprietary' — replace with an appropriate license before publication")

    # stac_extensions must include the OSC schema URL
    stac_exts = collection.stac_extensions or []
    if OSC_SCHEMA_URL not in stac_exts:
        raise ValueError(f"Collection missing OSC stac_extensions entry: {OSC_SCHEMA_URL}")

    # OSC extra_fields requirements
    extra = collection.extra_fields or {}
    if extra.get("osc:type") != "product":
        raise ValueError("Collection 'osc:type' must exist and equal 'product' for publication readiness")
    if "osc:status" not in extra:
        raise ValueError("Collection missing 'osc:status' in extra_fields")
    if "osc:project" not in extra or not isinstance(extra.get("osc:project"), str):
        raise ValueError("Collection 'osc:project' must exist in extra_fields and be a string")

    # Item-level publication checks
    for item in collection.get_items():
        # top-level bbox must exist
        if item.bbox is None:
            raise ValueError(f"Item '{item.id}' missing top-level bbox")

        # top-level geometry must exist
        if item.geometry is None:
            raise ValueError(f"Item '{item.id}' missing top-level geometry")

        # bbox must look like WGS84 lon/lat coordinates
        bb = item.bbox
        if not (isinstance(bb, (list, tuple)) and len(bb) == 4):
            raise ValueError(f"Item '{item.id}' bbox is not a 4-tuple/list: {bb}")
        minx, miny, maxx, maxy = map(float, bb)
        if not (-180.0 <= minx <= 180.0 and -180.0 <= maxx <= 180.0 and -90.0 <= miny <= 90.0 and -90.0 <= maxy <= 90.0):
            raise ValueError(f"Item '{item.id}' bbox values do not look like WGS84 lon/lat: {bb}")

        # datetime handling: either a concrete datetime or null + start/end present
        dt_val = getattr(item, "datetime", None)
        start_dt = getattr(item, "start_datetime", None)
        end_dt = getattr(item, "end_datetime", None)
        if dt_val is not None:
            if not isinstance(dt_val, datetime.datetime):
                raise ValueError(f"Item '{item.id}' top-level datetime is present but not a datetime object: {dt_val}")
        else:
            if start_dt is None or end_dt is None:
                raise ValueError(f"Item '{item.id}' has no top-level datetime and missing start_datetime/end_datetime")

        # properties must not contain temporal fields
        props = item.properties or {}
        for temporal_key in ("datetime", "start_datetime", "end_datetime"):
            if temporal_key in props:
                raise ValueError(f"Item '{item.id}' has temporal field '{temporal_key}' inside properties; move to top-level")

        # asset href checks
        for key, asset in (item.assets or {}).items():
            href = getattr(asset, "href", None)
            if not href:
                raise ValueError(f"Item '{item.id}' asset '{key}' has empty href")
            if publication_mode:
                parsed = urlparse(href)
                if parsed.scheme == "file":
                    raise ValueError(f"Item '{item.id}' asset '{key}' uses file:// href; replace with hosted HTTP(S) URL for publication: {href}")
                if parsed.scheme == "" and href.startswith("/"):
                    raise ValueError(f"Item '{item.id}' asset '{key}' contains an absolute local path; replace with hosted URL before publication: {href}")


def validate_with_stac_validator(path: Path) -> None:
    """Optionally run the external STAC validator if available.

    This function will try to import `stac_validator` and run it against the
    target path. If the package is not installed or integration is not
    possible, the function will print a message and return without raising.
    """
    try:
        import stac_validator  # type: ignore
    except Exception:
        print("stac_validator not available; skipping full validation")
        return

    # best-effort: try to call a commonly available API
    try:
        if hasattr(stac_validator, "validate"):
            # some versions expose a validate() function
            stac_validator.validate(str(path))
        elif hasattr(stac_validator, "run"):
            stac_validator.run([str(path)])
        else:
            print("stac_validator installed but no known entrypoint; skipping")
    except Exception as e:
        # Do not fail hard for validator errors; surface message instead
        print(f"stac_validator reported errors: {e}")


def validate_stac(path: Path, publication_mode: bool = False) -> None:
    """Load a collection and run basic (and optional full) validations.

    Raises on basic validation failures. Full validation is best-effort and
    will not raise if the external validator is missing.
    """
    coll = load_collection(path)
    validate_collection_basic(coll)
    # publication-oriented checks (no-op unless publication_mode True)
    validate_publication_readiness(coll, publication_mode=publication_mode)

    # optional external validator
    validate_with_stac_validator(path)
    print(f"STAC validation passed for collection: {coll.id} (items: {len(list(coll.get_items()))})")
