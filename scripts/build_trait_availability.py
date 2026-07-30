#!/usr/bin/env python3
"""Build the plant-trait dropdown availability manifest from STAC asset links."""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ITEMS = Path("stac_catalogs/stac_catalog_v1/items")
VISUALIZATION = Path("eodash/config/plant-trait-visualization.json")
OUTPUT = Path("eodash/config/trait-availability.json")
SUCCESS_STATUSES = range(200, 400)
MISSING_STATUSES = {404, 410}
RETRYABLE_STATUSES = {408, 425, 429, 500, 502, 503, 504}


def probe_asset(href: str, attempts: int = 3, timeout: int = 30) -> int:
    request = Request(href, method="HEAD", headers={"User-Agent": "trait-maps-availability/1"})
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=timeout) as response:
                status = response.status
            if status in SUCCESS_STATUSES or status in MISSING_STATUSES:
                return status
            if status not in RETRYABLE_STATUSES:
                raise RuntimeError(f"unexpected HTTP {status}: {href}")
        except HTTPError as error:
            if error.code in MISSING_STATUSES:
                return error.code
            if error.code not in RETRYABLE_STATUSES:
                raise RuntimeError(f"unexpected HTTP {error.code}: {href}") from error
        except (TimeoutError, URLError) as error:
            if attempt + 1 == attempts:
                raise RuntimeError(f"availability check failed: {href}: {error}") from error
        if attempt + 1 < attempts:
            time.sleep(2**attempt)
    raise RuntimeError(f"availability check did not complete: {href}")


def load_traits(items_directory: Path, visualization_path: Path) -> list[dict]:
    visualization = json.loads(visualization_path.read_text(encoding="utf-8"))
    asset_key = visualization["assetProducts"]["mean"]["assetKey"]
    traits = []
    for path in sorted(items_directory.glob("*.json")):
        item = json.loads(path.read_text(encoding="utf-8"))
        asset = item.get("assets", {}).get(asset_key)
        if not asset or not asset.get("href"):
            raise ValueError(f"{item.get('id', path.stem)}: missing primary asset {asset_key}")
        href = asset["href"]
        traits.append(
            {
                "id": item["id"],
                "title": item.get("properties", {}).get("trait_short_name")
                or item["id"],
                "assetKey": asset_key,
                "filename": href.rsplit("/", 1)[-1],
                "href": href,
            }
        )
    return traits


def build_manifest(items_directory: Path, visualization_path: Path, workers: int) -> dict:
    traits = load_traits(items_directory, visualization_path)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        statuses = list(executor.map(lambda trait: probe_asset(trait["href"]), traits))
    items = []
    for trait, status in zip(traits, statuses, strict=True):
        items.append(
            {
                **trait,
                "available": status in SUCCESS_STATUSES,
                "httpStatus": status,
            }
        )
    items.sort(key=lambda item: (item["title"], item["id"]))
    return {
        "sourceItems": items_directory.as_posix(),
        "items": items,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items", type=Path, default=ITEMS)
    parser.add_argument("--visualization", type=Path, default=VISUALIZATION)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    manifest = build_manifest(args.items, args.visualization, args.workers)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    available = sum(item["available"] for item in manifest["items"])
    print(
        f"Wrote {available} available and {len(manifest['items']) - available} "
        f"unavailable traits to {args.output}"
    )


if __name__ == "__main__":
    main()
