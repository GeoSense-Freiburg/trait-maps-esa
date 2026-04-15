"""Load and resolve trait and statistic metadata for parsed filenames.

This module provides small helpers to load JSON mapping files and to resolve
human-readable names/units for trait and statistic identifiers extracted from
filenames. Functions are defensive and return sensible fallbacks when inputs
are missing or mappings don't contain the requested keys.
"""

from pathlib import Path
from typing import Any, Dict, Optional, Union
import json
import re


def load_trait_metadata(path: Path) -> Dict[str, Any]:
    """Load trait mapping JSON from `path`.

    Args:
        path: path to a JSON file

    Returns:
        dict: parsed JSON object

    Raises:
        FileNotFoundError: if the file does not exist
        ValueError: if the file cannot be parsed as JSON
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Trait mapping file not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in trait mapping file {path}: {e}") from e
    return data if isinstance(data, dict) else {}


def load_stat_metadata(path: Path) -> Dict[str, Any]:
    """Load statistic mapping JSON from `path`.

    Args:
        path: path to a JSON file

    Returns:
        dict: parsed JSON object

    Raises:
        FileNotFoundError: if the file does not exist
        ValueError: if the file cannot be parsed as JSON
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Stat mapping file not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in stat mapping file {path}: {e}") from e
    return data if isinstance(data, dict) else {}


def _normalize(s: Union[str, int, None]) -> str:
    if s is None:
        return ""
    return re.sub(r"[^0-9a-z]+", "", str(s).lower())


def _find_best_match(mapping: Dict[str, Any], key: Optional[str]) -> Optional[str]:
    """Find a mapping key that best matches `key` using normalization.

    Returns the original mapping key when found, else None.
    """
    if not mapping:
        return None
    if key is None:
        return None
    # direct hit
    if key in mapping:
        return key

    norm_key = _normalize(key)
    # try matching normalized mapping keys
    for k in mapping.keys():
        if _normalize(k) == norm_key:
            return k

    # also try matching normalized values (if values are simple strings)
    for k, v in mapping.items():
        if isinstance(v, str) and _normalize(v) == norm_key:
            return k
        if isinstance(v, dict):
            # check common fields
            for fld in ("short", "long", "name", "stat_name"):
                vv = v.get(fld)
                if isinstance(vv, str) and _normalize(vv) == norm_key:
                    return k

    return None


def resolve_trait_metadata(trait_id: Optional[str], trait_mapping: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve a trait identifier into human-readable metadata.

    The function returns a normalized dict with keys:
        - trait_id
        - trait_short_name
        - trait_long_name
        - trait_unit

    If the trait cannot be resolved, sensible fallbacks (mostly None) are
    returned.
    """
    # Prefer direct string-key lookup (trait_mapping keys are numeric strings)
    chosen_key: Optional[str] = None
    if trait_id is None:
        return {"trait_id": None, "trait_short_name": None, "trait_long_name": None, "trait_unit": None}

    trait_key = str(trait_id)
    if trait_key in trait_mapping:
        chosen_key = trait_key
    else:
        # fallback to normalized/fuzzy matching
        chosen_key = _find_best_match(trait_mapping, trait_id)

    short_name = None
    long_name = None
    unit = None

    if chosen_key is not None:
        value = trait_mapping.get(chosen_key)
        if isinstance(value, dict):
            short_name = value.get("short") or value.get("short_name")
            long_name = value.get("long") or value.get("long_name") or value.get("description")
            unit = value.get("unit")
        elif isinstance(value, str):
            long_name = value
            short_name = None

    # sensible fallbacks
    if short_name is None:
        short_name = trait_key
    if long_name is None:
        long_name = short_name

    return {
        "trait_id": chosen_key if chosen_key is not None else trait_key,
        "trait_short_name": short_name,
        "trait_long_name": long_name,
        "trait_unit": unit,
    }


def resolve_stat_metadata(stat_id: Optional[str], stat_mapping: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve a statistic identifier into a normalized dict.

    Returns keys:
        - stat_id
        - stat_name

    If unresolved, returns None for stat_name and preserves stat_id.
    """
    # Prefer direct string-key lookup. Also support reverse lookup by stat
    # name: callers may pass a human-readable stat name (e.g. 'mean') and we
    # should return the numeric mapping key when available.
    if stat_id is None:
        return {"stat_id": None, "stat_name": None}

    stat_key = str(stat_id)
    chosen_key: Optional[str] = None

    # direct key hit
    if stat_key in stat_mapping:
        chosen_key = stat_key
    else:
        # attempt reverse lookup: if caller passed a stat name (e.g. 'mean'),
        # find a mapping entry whose value or value fields match that name.
        norm = _normalize(stat_key)
        for k, v in stat_mapping.items():
            if isinstance(v, str):
                if _normalize(v) == norm:
                    chosen_key = k
                    break
            elif isinstance(v, dict):
                for fld in ("stat_name", "name", "short", "long"):
                    vv = v.get(fld)
                    if isinstance(vv, str) and _normalize(vv) == norm:
                        chosen_key = k
                        break
                if chosen_key:
                    break

        # final fallback: use the fuzzy/normalized key matcher
        if chosen_key is None:
            chosen_key = _find_best_match(stat_mapping, stat_id)

    stat_name: Optional[str] = None
    if chosen_key is not None:
        value = stat_mapping.get(chosen_key)
        if isinstance(value, dict):
            stat_name = value.get("stat_name") or value.get("name")
        elif isinstance(value, str):
            stat_name = value

    # fallback: if stat_name still unknown, use the original input string
    if stat_name is None:
        stat_name = stat_key

    return {"stat_id": chosen_key if chosen_key is not None else stat_key, "stat_name": stat_name}


def build_metadata_record(parsed_filename: Dict[str, Any], trait_mapping: Dict[str, Any], stat_mapping: Dict[str, Any]) -> Dict[str, Any]:
    """Merge parsed filename info with trait and stat metadata.

    Args:
        parsed_filename: output of `parse_filename`
        trait_mapping: dict from `load_trait_metadata`
        stat_mapping: dict from `load_stat_metadata`

    Returns:
        merged metadata record with at least:
            filename, stem, trait_id, trait_short_name, trait_long_name,
            trait_unit, stat_id, stat_name
    """
    trait_id = parsed_filename.get("trait_id")
    # If parse_filename provided a human-readable stat_name but no numeric
    # stat_id, let resolve_stat_metadata attempt to map the name back to an id
    # by passing the parsed stat_name through.
    stat_id = parsed_filename.get("stat_id") or parsed_filename.get("stat_name")

    trait_meta = resolve_trait_metadata(trait_id, trait_mapping)
    stat_meta = resolve_stat_metadata(stat_id, stat_mapping)

    record: Dict[str, Any] = {}
    # preserve parsed fields
    record.update({k: parsed_filename.get(k) for k in ("filename", "stem")})
    record["tokens"] = parsed_filename.get("tokens")

    # trait fields
    record["trait_id"] = trait_meta.get("trait_id")
    record["trait_short_name"] = trait_meta.get("trait_short_name")
    record["trait_long_name"] = trait_meta.get("trait_long_name")
    record["trait_unit"] = trait_meta.get("trait_unit")

    # stat fields
    record["stat_id"] = stat_meta.get("stat_id")
    record["stat_name"] = stat_meta.get("stat_name")

    # keep other useful parsed fields if present
    for k in ("resolution", "version", "other_tokens"):
        if k in parsed_filename:
            record[k] = parsed_filename.get(k)

    return record
