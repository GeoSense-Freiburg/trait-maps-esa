from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pystac
import rasterio
from rasterio.transform import from_origin

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from esa_trait_publish.cli import main

RASTER_NAME = "X13_mean_Shrub_Tree_Grass_1km.tif"


def _build_output(
    output_dir: Path,
    maps_dir: Path,
    trait_metadata: Path,
    stat_metadata: Path,
    write_preview_assets: bool,
) -> None:
    args = [
        "--maps-dir",
        str(maps_dir),
        "--trait-metadata",
        str(trait_metadata),
        "--stat-metadata",
        str(stat_metadata),
        "--output-dir",
        str(output_dir),
        "--allow-unknown-status",
    ]
    if write_preview_assets:
        args.append("--write-preview-assets")
    main(args)


def _write_metadata_files(base_dir: Path) -> tuple[Path, Path]:
    metadata_dir = base_dir / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)

    trait_metadata = metadata_dir / "trait_mapping.json"
    trait_metadata.write_text(
        json.dumps(
            {
                "13": {
                    "short": "Leaf C",
                    "long": "Leaf carbon (C) content per leaf dry mass",
                    "unit": "mg g⁻¹",
                }
            }
        ),
        encoding="utf-8",
    )

    stat_metadata = metadata_dir / "trait_stat_mapping.json"
    stat_metadata.write_text(json.dumps({"1": "mean"}), encoding="utf-8")

    return trait_metadata, stat_metadata


def _prepare_maps_dir(base_dir: Path) -> Path:
    maps_dir = base_dir / "maps"
    maps_dir.mkdir(parents=True, exist_ok=True)

    raster_path = maps_dir / RASTER_NAME
    width = 128
    height = 96
    transform = from_origin(-17367530.445161372, 7342230.205017056, 1000.0, 1000.0)
    profile = {
        "driver": "GTiff",
        "width": width,
        "height": height,
        "count": 3,
        "dtype": "int16",
        "crs": "EPSG:6933",
        "transform": transform,
        "nodata": -32768,
        "tiled": True,
        "blockxsize": 32,
        "blockysize": 32,
        "compress": "deflate",
    }

    rows = np.linspace(-1.0, 1.0, height, dtype=np.float32)[:, None]
    cols = np.linspace(-1.0, 1.0, width, dtype=np.float32)[None, :]
    mean_band = np.round((rows + cols) * 8000).astype(np.int16)
    cv_band = np.round((rows * cols + 1.0) * 12000).astype(np.int16)
    aoi_band = np.where(rows + cols > 0, 1, 0).astype(np.int16)

    mean_band[:6, :6] = -32768
    cv_band[-6:, -6:] = -32768
    aoi_band[:4, -4:] = -32768

    with rasterio.open(raster_path, "w", **profile) as dst:
        dst.write(mean_band, 1)
        dst.write(cv_band, 2)
        dst.write(aoi_band, 3)
        dst.set_band_description(1, "Leaf C (mean)")
        dst.set_band_description(2, "Coefficient of Variation")
        dst.set_band_description(3, "Area of Applicability mask")
        dst.scales = [0.0032486534766512296, 1.958739654434767e-05, 1.0]
        dst.offsets = [460.00291048945945, 0.6420001681326539, 0.0]

    return maps_dir


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_default_build_does_not_write_preview_assets(tmp_path: Path) -> None:
    maps_dir = _prepare_maps_dir(tmp_path)
    trait_metadata, stat_metadata = _write_metadata_files(tmp_path)
    output_dir = tmp_path / "output"

    _build_output(output_dir, maps_dir, trait_metadata, stat_metadata, write_preview_assets=False)

    assert not (output_dir / "previews").exists()

    item_path = output_dir / "items" / "X13_mean_Shrub_Tree_Grass_1km.json"
    item = _load_json(item_path)

    preview_keys = [key for key in item.get("assets", {}) if key.startswith("preview_")]
    assert preview_keys == []
    assert set(item["assets"]) == {"data"}


def test_preview_build_writes_pngs_and_item_assets(tmp_path: Path) -> None:
    baseline_maps_dir = _prepare_maps_dir(tmp_path / "baseline")
    preview_maps_dir = _prepare_maps_dir(tmp_path / "preview")
    trait_metadata, stat_metadata = _write_metadata_files(tmp_path)

    baseline_output = tmp_path / "baseline-output"
    preview_output = tmp_path / "preview-output"

    _build_output(baseline_output, baseline_maps_dir, trait_metadata, stat_metadata, write_preview_assets=False)
    _build_output(preview_output, preview_maps_dir, trait_metadata, stat_metadata, write_preview_assets=True)

    baseline_collection = _load_json(baseline_output / "collection.json")
    preview_collection = _load_json(preview_output / "collection.json")
    assert preview_collection == baseline_collection

    baseline_catalog = _load_json(baseline_output / "catalog.json")
    preview_catalog = _load_json(preview_output / "catalog.json")
    assert preview_catalog == baseline_catalog

    item_path = preview_output / "items" / "X13_mean_Shrub_Tree_Grass_1km.json"
    item = _load_json(item_path)

    previews_dir = preview_output / "previews"
    assert previews_dir.exists()

    bands = item["assets"]["data"]["raster:bands"]
    preview_assets = {key: value for key, value in item["assets"].items() if key.startswith("preview_")}

    expected_keys = {
        "preview_trait_mean",
        "preview_coefficient_of_variation",
        "preview_area_of_applicability",
    }
    assert set(preview_assets) == expected_keys
    assert len(list(previews_dir.glob("*.png"))) == len(bands)

    expected_files = {
        "X13_mean_Shrub_Tree_Grass_1km_trait_mean.png",
        "X13_mean_Shrub_Tree_Grass_1km_coefficient_of_variation.png",
        "X13_mean_Shrub_Tree_Grass_1km_area_of_applicability.png",
    }
    assert {path.name for path in previews_dir.glob("*.png")} == expected_files

    for key, asset in preview_assets.items():
        assert asset["type"] == "image/png"
        assert asset["roles"] == ["thumbnail", "overview"]
        assert asset["href"].startswith("../previews/")
        assert asset["title"].endswith("preview")

    baseline_item = _load_json(baseline_output / "items" / "X13_mean_Shrub_Tree_Grass_1km.json")
    assert item["assets"]["data"] == baseline_item["assets"]["data"]

    catalog = pystac.Catalog.from_file(str(preview_output / "catalog.json"))
    catalog.resolve_links()
    catalog.validate_all()
