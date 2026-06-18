#!/usr/bin/env python3
"""Validate a local STAC collection for ESA EarthCODE / OSC readiness.

Usage:
    python scripts/validate_esa_stac.py outputs/stac_maps

This script performs pragmatic checks for:
- STAC core structure
- ESA OSC collection metadata
- scientific DOI/citation metadata
- projection metadata on items
- relative STAC links
- hosted asset hrefs
- absence of local filesystem paths

It is not a replacement for `stac-validator`, but complements it with
project-specific ESA/OSC publication-readiness checks.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


OSC_EXTENSION = "https://stac-extensions.github.io/osc/v1.0.0/schema.json"
SCIENTIFIC_EXTENSION = "https://stac-extensions.github.io/scientific/v1.0.0/schema.json"
PROJECTION_EXTENSION = "https://stac-extensions.github.io/projection/v2.0.0/schema.json"

EXPECTED_COLLECTION_ID = "global-plant-trait-maps"
EXPECTED_OSC_TYPE = "product"
EXPECTED_OSC_PROJECT = "FORTRACK"
EXPECTED_LICENSE = "CC-BY-4.0"
EXPECTED_DOI = "10.5281/zenodo.14646322"
EXPECTED_DOI_URL = "https://doi.org/10.5281/zenodo.14646322"
EXPECTED_ASSET_PREFIX = "https://zenodo.org/records/14646322/files/"
EXPECTED_PUBLICATION_DOI = "https://doi.org/10.1101/2025.03.10.641660"
EXPECTED_DOCUMENTATION_URL = "https://planttraits.earth/"
EXPECTED_TEMPORAL_START = "2026-01-30T00:00:00Z"
EXPECTED_TEMPORAL_END = "2026-01-30T23:59:59Z"


class ValidationReport:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    @property
    def ok(self) -> bool:
        return not self.errors

    def print(self) -> None:
        if self.errors:
            print("\nERRORS")
            for msg in self.errors:
                print(f"  - {msg}")

        if self.warnings:
            print("\nWARNINGS")
            for msg in self.warnings:
                print(f"  - {msg}")

        if not self.errors and not self.warnings:
            print("\nPASS: no issues found.")
        elif not self.errors:
            print("\nPASS with warnings.")
        else:
            print("\nFAIL.")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def is_local_path(value: str) -> bool:
    """Return True if href looks like a local filesystem path."""
    if value.startswith(("/", "file://")):
        return True
    if len(value) > 2 and value[1:3] == ":\\":
        return True
    return False


def is_remote_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def require_field(obj: dict[str, Any], field: str, where: str, report: ValidationReport) -> Any:
    if field not in obj:
        report.error(f"{where}: missing required field `{field}`")
        return None
    return obj[field]


def get_links(obj: dict[str, Any], rel: str) -> list[dict[str, Any]]:
    return [link for link in obj.get("links", []) if link.get("rel") == rel]


def validate_collection(collection: dict[str, Any], collection_path: Path, report: ValidationReport) -> list[Path]:
    where = "collection"

    if collection.get("type") != "Collection":
        report.error("collection: `type` must be `Collection`")

    if collection.get("stac_version") != "1.1.0":
        report.warn(f"collection: expected `stac_version` 1.1.0, got {collection.get('stac_version')}")

    if collection.get("id") != EXPECTED_COLLECTION_ID:
        report.warn(f"collection: expected id `{EXPECTED_COLLECTION_ID}`, got `{collection.get('id')}`")

    for field in ["title", "description", "extent", "license", "links"]:
        require_field(collection, field, where, report)

    if collection.get("license") != EXPECTED_LICENSE:
        report.warn(f"collection: expected license `{EXPECTED_LICENSE}`, got `{collection.get('license')}`")

    extensions = collection.get("stac_extensions", [])
    if OSC_EXTENSION not in extensions:
        report.error("collection: missing OSC extension")
    if SCIENTIFIC_EXTENSION not in extensions:
        report.warn("collection: missing scientific extension, although sci:* fields are expected")

    if collection.get("osc:type") != EXPECTED_OSC_TYPE:
        report.error(f"collection: `osc:type` should be `{EXPECTED_OSC_TYPE}`")

    if not isinstance(collection.get("osc:project"), str):
        report.error("collection: `osc:project` must be a string")
    elif collection.get("osc:project") != EXPECTED_OSC_PROJECT:
        report.warn(f"collection: expected `osc:project` `{EXPECTED_OSC_PROJECT}`, got `{collection.get('osc:project')}`")

    if "osc:status" not in collection:
        report.error("collection: missing `osc:status`")
    elif collection["osc:status"] not in {"draft", "ongoing", "completed", "finished"}:
        report.warn(f"collection: unusual `osc:status`: {collection['osc:status']}")

    if collection.get("sci:doi") != EXPECTED_DOI:
        report.warn(f"collection: expected sci:doi `{EXPECTED_DOI}`, got `{collection.get('sci:doi')}`")

    if "sci:citation" not in collection:
        report.warn("collection: missing `sci:citation`")

    if "published" not in collection:
        report.warn("collection: missing publication date field `published`")

    # Collection temporal extent: for this static product we expect open interval.
    interval = (
        collection.get("extent", {})
        .get("temporal", {})
        .get("interval")
    )
        expected_interval = [[EXPECTED_TEMPORAL_START, EXPECTED_TEMPORAL_END]]
        if interval != expected_interval:
            report.warn(f"collection: expected temporal extent {expected_interval}, got {interval}")

    # Links.
    links = collection.get("links", [])
    if not links:
        report.error("collection: missing links")

    for link in links:
        href = link.get("href")
        if isinstance(href, str) and is_local_path(href):
            report.error(f"collection: local filesystem href found in link: {href}")

    if not get_links(collection, "root"):
        report.warn("collection: missing root link")

    if not get_links(collection, "self"):
        report.warn("collection: missing self link")

    if not get_links(collection, "describedby"):
        report.warn("collection: missing describedby link to DOI/record")

    cite_as = get_links(collection, "cite-as")
    if not cite_as:
        report.warn("collection: missing cite-as link to DOI")
    elif not any(link.get("href") == EXPECTED_DOI_URL for link in cite_as):
        report.warn("collection: cite-as link does not point to expected DOI URL")

        # Check for publication DOI link
        pub_dois = get_links(collection, "describedby")
        if not any(link.get("href") == EXPECTED_PUBLICATION_DOI for link in pub_dois):
            report.warn(f"collection: describedby link should point to publication DOI {EXPECTED_PUBLICATION_DOI}")

        # Check for documentation link
        via_links = get_links(collection, "via")
        if not via_links:
            report.warn("collection: missing via link to documentation")
        elif not any(link.get("href") == EXPECTED_DOCUMENTATION_URL for link in via_links):
            report.warn(f"collection: via link should point to {EXPECTED_DOCUMENTATION_URL}")

        # Check for osc:missions
        missions = collection.get("osc:missions")
        if not missions:
            report.warn("collection: missing osc:missions")
        elif not isinstance(missions, list):
            report.warn("collection: osc:missions must be a list")
        else:
            if "modis" not in missions:
                report.warn("collection: osc:missions should include 'modis'")
            if "in-situ-observations" not in missions:
                report.warn("collection: osc:missions should include 'in-situ-observations'")

    item_links = get_links(collection, "item")
    if not item_links:
        report.error("collection: no item links found")

    item_paths: list[Path] = []
    for link in item_links:
        href = link.get("href")
        if not isinstance(href, str):
            report.error("collection: item link missing href")
            continue
        if is_local_path(href):
            report.error(f"collection: item link uses local path: {href}")
        if is_remote_url(href):
            report.warn(f"collection: item link is remote; expected relative local STAC link: {href}")

        item_path = (collection_path.parent / href).resolve()
        item_paths.append(item_path)
        if not item_path.exists():
            report.error(f"collection: item link target does not exist: {href}")

    # Summaries and item_assets.
    if "summaries" not in collection:
        report.warn("collection: missing summaries")
    else:
        summaries = collection["summaries"]
        for key in ["trait_short_name", "trait_unit", "stat_name", "proj:code"]:
            if key not in summaries:
                report.warn(f"collection summaries: missing `{key}`")

    if "item_assets" not in collection:
        report.warn("collection: missing item_assets")
    else:
        data_asset = collection["item_assets"].get("data")
        if not data_asset:
            report.warn("collection item_assets: missing `data` asset definition")
        else:
            if "image/tiff" not in data_asset.get("type", ""):
                report.warn("collection item_assets.data: expected GeoTIFF media type")
            if "data" not in data_asset.get("roles", []):
                report.warn("collection item_assets.data: expected role `data`")

    return item_paths


def validate_item(item: dict[str, Any], item_path: Path, report: ValidationReport) -> None:
    where = f"item {item_path.name}"

    if item.get("type") != "Feature":
        report.error(f"{where}: `type` must be `Feature`")

    for field in ["id", "geometry", "bbox", "properties", "assets", "links", "collection", "datetime"]:
        require_field(item, field, where, report)

    if item.get("collection") != EXPECTED_COLLECTION_ID:
        report.error(f"{where}: collection must be `{EXPECTED_COLLECTION_ID}`")

    # datetime: current project convention is publication-date timestamp.
    datetime_value = item.get("datetime")
    if datetime_value is None:
        report.error(
            f"{where}: datetime is null. Current project convention is to use publication/version date."
        )
    elif not isinstance(datetime_value, str):
        report.error(f"{where}: datetime must be an ISO timestamp string")

    props = item.get("properties", {})
    if "datetime" in props:
        report.error(f"{where}: datetime must not be inside properties")

    if "start_datetime" in item or "end_datetime" in item:
        report.warn(f"{where}: start_datetime/end_datetime present; not expected for static no-span products")

    # Geometry / bbox.
    bbox = item.get("bbox")
    if isinstance(bbox, list) and len(bbox) == 4:
        minx, miny, maxx, maxy = bbox
        if not (-180 <= minx <= 180 and -180 <= maxx <= 180 and -90 <= miny <= 90 and -90 <= maxy <= 90):
            report.error(f"{where}: bbox does not look like WGS84 lon/lat: {bbox}")
    else:
        report.error(f"{where}: bbox must be a list of four values")

    geometry = item.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type") != "Polygon":
        report.warn(f"{where}: geometry should be a WGS84 Polygon")

    # Extensions / projection metadata.
    extensions = item.get("stac_extensions", [])
    if PROJECTION_EXTENSION not in extensions:
        report.error(f"{where}: missing projection extension")

    if "proj:code" not in props:
        report.error(f"{where}: missing proj:code")
    elif props["proj:code"] != "EPSG:6933":
        report.warn(f"{where}: expected proj:code EPSG:6933, got {props['proj:code']}")

    if "proj:bbox" not in props:
        report.error(f"{where}: missing proj:bbox")

    # Trait/stat metadata.
    for field in ["trait_id", "trait_short_name", "trait_long_name", "trait_unit", "stat_id", "stat_name"]:
        if field not in props:
            report.warn(f"{where}: missing `{field}` in properties")

    if "title" not in props:
        report.warn(f"{where}: missing human-readable properties.title")
    if "description" not in props:
        report.warn(f"{where}: missing properties.description")

    # Links.
    for link in item.get("links", []):
        href = link.get("href")
        if isinstance(href, str) and is_local_path(href):
            report.error(f"{where}: local filesystem href found in link: {href}")

    if not get_links(item, "root"):
        report.warn(f"{where}: missing root link")
    if not get_links(item, "parent"):
        report.warn(f"{where}: missing parent link")
    if not get_links(item, "collection"):
        report.error(f"{where}: missing collection link")
    if not get_links(item, "self"):
        report.warn(f"{where}: missing self link")

    # Assets.
    assets = item.get("assets", {})
    data = assets.get("data")
    if not data:
        report.error(f"{where}: missing assets.data")
        return

    href = data.get("href")
    if not isinstance(href, str):
        report.error(f"{where}: assets.data.href missing or not string")
    else:
        if is_local_path(href):
            report.error(f"{where}: assets.data.href is local filesystem path: {href}")
        if not href.startswith(EXPECTED_ASSET_PREFIX):
            report.warn(f"{where}: assets.data.href does not start with expected Zenodo prefix: {href}")

    if "image/tiff" not in data.get("type", ""):
        report.warn(f"{where}: assets.data.type does not look like GeoTIFF/COG")

    if "data" not in data.get("roles", []):
        report.warn(f"{where}: assets.data.roles should include `data`")

    if "title" not in data:
        report.warn(f"{where}: assets.data missing title; useful for catalog/APEx display")


def validate_stac_directory(stac_dir: Path) -> ValidationReport:
    report = ValidationReport()

    collection_path = stac_dir / "collection.json"
    if not collection_path.exists():
        report.error(f"Missing collection.json in {stac_dir}")
        return report

    try:
        collection = load_json(collection_path)
    except Exception as exc:
        report.error(f"Could not read collection.json: {exc}")
        return report

    item_paths = validate_collection(collection, collection_path, report)

    for item_path in item_paths:
        if not item_path.exists():
            continue
        try:
            item = load_json(item_path)
        except Exception as exc:
            report.error(f"Could not read item {item_path}: {exc}")
            continue
        validate_item(item, item_path, report)

    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a local STAC directory for ESA EarthCODE / OSC readiness."
    )
    parser.add_argument(
        "stac_dir",
        type=Path,
        help="Directory containing collection.json, e.g. outputs/stac_maps",
    )
    args = parser.parse_args()

    report = validate_stac_directory(args.stac_dir)
    report.print()

    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())