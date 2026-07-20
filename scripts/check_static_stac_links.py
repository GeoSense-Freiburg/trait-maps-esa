#!/usr/bin/env python3
"""Check that local links in the canonical static STAC work on any site base."""

from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import urlparse

from stac_catalog_utils import is_remote_href, resolve_local_href, walk_static_stac


ROOT = Path("stac_catalogs/stac_catalog_v1/catalog.json")
METADATA_RELS = {"self", "root", "parent", "child", "collection", "item"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=ROOT)
    args = parser.parse_args()
    failures: list[str] = []
    warnings: list[str] = []
    documents = walk_static_stac(args.catalog)
    local_links = 0
    remote_links = 0
    remote_assets = 0

    for path, document in documents:
        for link in document.get("links", []):
            href = link.get("href")
            rel = link.get("rel", "")
            if not isinstance(href, str) or not href:
                failures.append(f"{path}: {rel!r} link has no href")
                continue
            parsed = urlparse(href)
            if is_remote_href(href):
                remote_links += 1
                continue
            if parsed.path.startswith("/"):
                failures.append(
                    f"{path}: root-relative {rel!r} link breaks on a GitHub Pages project path: {href}"
                )
            target = resolve_local_href(path, href)
            local_links += 1
            if rel in METADATA_RELS and (target is None or not target.is_file()):
                failures.append(f"{path}: {rel!r} target does not exist: {href}")

        for asset_key, asset in document.get("assets", {}).items():
            href = asset.get("href")
            if not isinstance(href, str) or not href:
                failures.append(f"{path}: asset {asset_key!r} has no href")
            elif is_remote_href(href):
                remote_assets += 1
            else:
                parsed = urlparse(href)
                if parsed.path.startswith("/"):
                    failures.append(f"{path}: root-relative asset breaks on project Pages: {href}")
                target = resolve_local_href(path, href)
                if target is None or not target.is_file():
                    failures.append(f"{path}: local asset {asset_key!r} does not exist: {href}")

    if len(documents) < 3:
        warnings.append("Traversal found fewer than a catalog, collection, and item")
    for warning in warnings:
        print(f"WARNING: {warning}")
    for failure in failures:
        print(f"ERROR: {failure}")
    print(
        f"Checked {len(documents)} STAC documents, {local_links} local links, "
        f"{remote_links} remote metadata links, and {remote_assets} remote assets."
    )
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
