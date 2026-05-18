#!/usr/bin/env python3
"""Check whether a STAC item's bbox matches the raster bounds transformed to WGS84."""

import argparse
import json
from pathlib import Path

import rasterio
from rasterio.warp import transform_bounds


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def compare_bounds(raster_path: Path, stac_item_path: Path, tolerance: float = 1e-4) -> None:
    item = load_json(stac_item_path)

    if "bbox" not in item:
        raise ValueError(f"No bbox found in STAC item: {stac_item_path}")

    stac_bbox = item["bbox"]

    with rasterio.open(raster_path) as src:
        native_bounds = src.bounds
        native_crs = src.crs

        if native_crs is None:
            raise ValueError(f"Raster has no CRS: {raster_path}")

        wgs84_bounds = transform_bounds(
            native_crs,
            "EPSG:4326",
            *native_bounds,
            densify_pts=21,
        )

    print("\nRaster:", raster_path)
    print("STAC item:", stac_item_path)

    print("\nNative CRS:", native_crs)
    print("Native raster bounds:")
    print(list(native_bounds))

    print("\nRaster bounds transformed to WGS84:")
    print(list(wgs84_bounds))

    print("\nSTAC bbox:")
    print(stac_bbox)

    diffs = [abs(a - b) for a, b in zip(wgs84_bounds, stac_bbox)]
    matches = all(diff <= tolerance for diff in diffs)

    print("\nCoordinate differences:")
    labels = ["min_lon", "min_lat", "max_lon", "max_lat"]
    for label, raster_val, stac_val, diff in zip(labels, wgs84_bounds, stac_bbox, diffs):
        print(f"{label}: raster={raster_val:.8f}, stac={stac_val:.8f}, diff={diff:.8f}")

    print("\nResult:")
    if matches:
        print("PASS: STAC bbox matches transformed raster bounds.")
    else:
        print("FAIL: STAC bbox does not match transformed raster bounds.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare raster bounds with STAC item bbox.")
    parser.add_argument("--raster", required=True, type=Path, help="Path to raster file.")
    parser.add_argument("--item", required=True, type=Path, help="Path to STAC item JSON.")
    parser.add_argument("--tolerance", type=float, default=1e-4, help="Allowed coordinate difference.")

    args = parser.parse_args()
    compare_bounds(args.raster, args.item, args.tolerance)


if __name__ == "__main__":
    main()