"""Small helpers for traversing the repository's canonical static STAC tree."""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from urllib.parse import unquote, urlparse


TRAVERSAL_RELS = {"child", "collection", "item"}


def is_remote_href(href: str) -> bool:
    return urlparse(href).scheme.lower() in {"http", "https", "s3"}


def resolve_local_href(document_path: Path, href: str) -> Path | None:
    """Resolve a local STAC link, returning ``None`` for remote URLs."""
    parsed = urlparse(href)
    if parsed.scheme or parsed.netloc:
        return None
    return (document_path.parent / unquote(parsed.path)).resolve()


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def walk_static_stac(root: Path) -> list[tuple[Path, dict]]:
    """Follow local child/collection/item links once, without following cycles."""
    queue = deque([root.resolve()])
    seen: set[Path] = set()
    documents: list[tuple[Path, dict]] = []
    while queue:
        path = queue.popleft()
        if path in seen:
            continue
        seen.add(path)
        document = load_json(path)
        documents.append((path, document))
        for link in document.get("links", []):
            if link.get("rel") not in TRAVERSAL_RELS:
                continue
            href = link.get("href")
            if not isinstance(href, str) or is_remote_href(href):
                continue
            target = resolve_local_href(path, href)
            if target is not None:
                queue.append(target)
    return documents


def iter_items(root: Path) -> list[tuple[Path, dict]]:
    return [
        (path, document)
        for path, document in walk_static_stac(root)
        if document.get("type") == "Feature" and isinstance(document.get("assets"), dict)
    ]


def iter_tiff_assets(root: Path):
    for path, item in iter_items(root):
        for asset_key, asset in item.get("assets", {}).items():
            media_type = str(asset.get("type", "")).lower()
            href = str(asset.get("href", ""))
            if "tiff" in media_type or href.lower().split("?", 1)[0].endswith((".tif", ".tiff")):
                yield path, item, asset_key, asset
