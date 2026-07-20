#!/usr/bin/env python3
"""Derive the EO Dashboard asset inventory from the canonical STAC catalog."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from stac_catalog_utils import iter_items, load_json


ROOT = Path("stac_catalogs/stac_catalog_v1/catalog.json")
OUTPUT = Path("eodash/config/asset-inventory.json")
BAND_NAMES = {
    "mean": "trait_mean",
    "cov": "coefficient_of_variation",
    "aoa": "area_of_applicability",
}


def classified_assets(item: dict) -> dict:
    matches: dict[str, dict] = {}
    for asset_key, asset in item.get("assets", {}).items():
        bands = asset.get("raster:bands", [])
        for index, band in enumerate(bands, start=1):
            for product, expected_name in BAND_NAMES.items():
                if band.get("name") != expected_name:
                    continue
                if product in matches:
                    raise ValueError(f"{item['id']}: duplicate {product} band metadata")
                matches[product] = {
                    "assetKey": asset_key,
                    "href": asset.get("href"),
                    "type": asset.get("type"),
                    "roles": asset.get("roles", []),
                    "band": index,
                    "bandName": band.get("name"),
                    "description": band.get("description"),
                    "unit": band.get("unit"),
                    "dataType": band.get("data_type"),
                    "nodata": band.get("nodata"),
                    "scale": band.get("scale", 1.0),
                    "offset": band.get("offset", 0.0),
                    "overviews": band.get("overviews", []),
                }
    missing = BAND_NAMES.keys() - matches.keys()
    if missing:
        raise ValueError(f"{item['id']}: missing explicit raster band metadata for {sorted(missing)}")
    return matches


def build_inventory(root: Path) -> dict:
    root_document = load_json(root)
    collections: dict[str, dict] = {}
    for path, item in iter_items(root):
        collection_id = item.get("collection")
        if not collection_id:
            raise ValueError(f"{path}: item has no collection id")
        collection = collections.setdefault(collection_id, {"id": collection_id, "items": []})
        collection["items"].append(
            {
                "id": item["id"],
                "title": item.get("properties", {}).get("trait_short_name")
                or item.get("properties", {}).get("title")
                or item["id"],
                "datetime": item.get("properties", {}).get("datetime"),
                "bbox": item.get("bbox"),
                "geometry": item.get("geometry"),
                "projection": {
                    "code": item.get("properties", {}).get("proj:code"),
                    "bbox": item.get("properties", {}).get("proj:bbox"),
                    "shape": item.get("properties", {}).get("proj:shape"),
                    "transform": item.get("properties", {}).get("proj:transform"),
                },
                "assets": classified_assets(item),
            }
        )
    for collection in collections.values():
        collection["items"].sort(key=lambda value: value["id"])
    return {
        "sourceCatalog": root.as_posix(),
        "catalogId": root_document.get("id"),
        "stacVersion": root_document.get("stac_version"),
        "collections": sorted(collections.values(), key=lambda value: value["id"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    inventory = build_inventory(args.catalog)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(inventory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    count = sum(len(collection["items"]) for collection in inventory["collections"])
    print(f"Wrote {count} canonical STAC items to {args.output}")


if __name__ == "__main__":
    main()
