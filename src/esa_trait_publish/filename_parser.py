"""Filename parsing utilities for ESA trait products.

Simple utilities to tokenize and parse raster filenames found in
`data/global_trait_maps/`. The parser is designed to be resilient: it
tokenizes on common separators, attempts to infer a trait identifier and a
statistic identifier, and returns other useful tokens such as resolution and
version. When mapping files are present in `metadata/`, the parser will try
to match inferred IDs to those mappings but will not raise if mappings are
missing.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import re
import difflib


SEP_RE = re.compile(r"[_\-\s\.]+")


def tokenize_filename(path: Path | str) -> List[str]:
    """Split a filename stem into normalized tokens.

    Examples:
        X1080_mean_Shrub_Tree_Grass_1km.tif -> ["x1080","mean","shrub","tree","grass","1km"]

    Args:
        path: path to the file (Path or str)

    Returns:
        list of lower-cased tokens (no extension)
    """
    stem = Path(path).stem
    raw_tokens = SEP_RE.split(stem)
    return [t.lower() for t in raw_tokens if t]


def _load_metadata_dir() -> Dict[str, Dict[str, Any]]:
    """Deprecated internal helper kept for backward compatibility.

    NOTE: parsing should not rely on loading metadata. This helper remains for
    historical reasons but parse_filename now extracts tokens and identifiers
    without resolving them against the metadata files.
    """
    return {"traits": {}, "stats": {}}


def _normalize_token(s: Any) -> str:
    """Normalize a value for loose matching: lowercase alphanumerics only."""
    if s is None:
        return ""
    return re.sub(r"[^0-9a-z]+", "", str(s).lower())


def normalize_trait_token(token: str) -> Optional[str]:
    """Normalize a trait token like 'X1080' or '1080' to '1080'.

    Returns the numeric trait id string when present, else None.
    """
    if not isinstance(token, str):
        return None
    m = re.match(r"^[xX]?(\d+)$", token)
    if m:
        return m.group(1)
    return None


def normalize_stat_token(token: str) -> Optional[str]:
    """Normalize a statistic token. Returns the lowercase stat name when
    token looks like a statistic (e.g. 'mean', 'std'). Returns None otherwise.
    """
    if not isinstance(token, str):
        return None
    t = token.lower()
    # common statistic names
    STAT_NAMES = {"mean", "median", "std", "stddev", "min", "max", "sum", "count", "mode"}
    if t in STAT_NAMES:
        return t
    # also accept 'mean' spelled out or short forms; simple heuristic: all-alpha small token
    if re.fullmatch(r"[a-z]{3,10}", t):
        return t
    return None


def parse_filename(path: Path | str) -> Dict[str, Any]:
    """Parse a raster filename into structured components.

    Returned dictionary contains at least the keys `filename` and `stem`.
    The parser will try to infer `trait_id` and `stat_id` and will include
    optional fields `resolution`, `version`, and `other_tokens`.

    Args:
        path: path to raster file

    Returns:
        dict with parsed fields. Fields not found are set to None.
    """
    p = Path(path)
    filename = p.name
    stem = p.stem
    tokens = tokenize_filename(p)

    # Do not resolve against metadata here: simply extract identifiers from tokens.
    trait_id: Optional[str] = None
    stat_id: Optional[str] = None
    stat_name: Optional[str] = None
    resolution: Optional[str] = None
    version: Optional[str] = None

    used = set()

    # find trait token (prefer first occurrence of X<digits> or <digits>)
    trait_index = None
    for i, t in enumerate(tokens):
        tid = normalize_trait_token(t)
        if tid:
            trait_id = tid
            trait_index = i
            used.add(i)
            break

    # if trait found and next token looks like a stat name, take it
    if trait_index is not None and trait_index + 1 < len(tokens):
        cand = tokens[trait_index + 1]
        sname = normalize_stat_token(cand)
        if sname:
            stat_name = sname
            used.add(trait_index + 1)

    # otherwise, look for an explicit stat token anywhere (common names)
    if stat_name is None:
        for i, t in enumerate(tokens):
            if i in used:
                continue
            sname = normalize_stat_token(t)
            if sname:
                stat_name = sname
                used.add(i)
                break

    # resolution like 1km, 100m
    for i, t in enumerate(tokens):
        if i in used:
            continue
        if re.match(r"^\d+(m|km)$", t):
            resolution = t
            used.add(i)
            break

    # version like v1, v1.0
    for i, t in enumerate(tokens):
        if i in used:
            continue
        if re.match(r"^v\d+(?:[\.\d]*)$", t):
            version = t
            used.add(i)
            break

    other_tokens = [t for i, t in enumerate(tokens) if i not in used]

    return {
        "filename": filename,
        "stem": stem,
        "tokens": tokens,
        "trait_id": trait_id,
        "stat_id": stat_id,
        "stat_name": stat_name,
        "resolution": resolution,
        "version": version,
        "other_tokens": other_tokens,
    }


def debug_parse_examples(directory: Path | str) -> None:
    """Print parsed filenames for all rasters in `directory` (helpful for debug).

    Args:
        directory: path to directory containing rasters
    """
    d = Path(directory)
    for p in sorted(d.iterdir()):
        if p.is_file() and p.suffix.lower() in {".tif", ".tiff"}:
            print(p.name, "->", parse_filename(p))
