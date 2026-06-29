from pathlib import Path

import json

import pystac

from esa_trait_publish.config import RENDER_EXTENSION
from esa_trait_publish.stac_builder import build_collection_from_directory, save_collection


REPO_ROOT = Path(__file__).resolve().parents[1]
MAPS_DIR = REPO_ROOT / "data" / "global_trait_maps" / "experimental"
TRAIT_METADATA = REPO_ROOT / "metadata_earth_code" / "trait_mapping.json"
STAT_METADATA = REPO_ROOT / "metadata_earth_code" / "trait_stat_mapping.json"


def _write_collection(output_dir: Path, include_render_extension: bool) -> dict:
	collection = build_collection_from_directory(
		MAPS_DIR,
		TRAIT_METADATA,
		STAT_METADATA,
		include_render_extension=include_render_extension,
	)
	save_collection(collection, output_dir)
	item_path = next((output_dir / "items").glob("*.json"))
	with item_path.open("r", encoding="utf-8") as handle:
		return json.load(handle)


def test_render_extension_flag_controls_item_metadata(tmp_path: Path) -> None:
	without_render = _write_collection(tmp_path / "without-render", include_render_extension=False)
	assert RENDER_EXTENSION not in without_render.get("stac_extensions", [])
	assert "renders" not in (without_render.get("properties") or {})

	with_render = _write_collection(tmp_path / "with-render", include_render_extension=True)
	assert RENDER_EXTENSION in with_render.get("stac_extensions", [])

	renders = (with_render.get("properties") or {}).get("renders")
	assert renders is not None
	assert set(renders) == {"mean", "cv", "aoa"}
	assert renders["mean"] == {
		"title": "Trait Mean",
		"assets": ["data"],
		"bidx": [1],
		"colormap_name": "viridis",
	}
	assert renders["cv"] == {
		"title": "Coefficient of Variation",
		"assets": ["data"],
		"bidx": [2],
		"colormap_name": "magma",
	}
	assert renders["aoa"] == {
		"title": "Area of Applicability",
		"assets": ["data"],
		"bidx": [3],
		"colormap_name": "gray",
	}

	catalog = pystac.Catalog.from_file(str((tmp_path / "with-render") / "catalog.json"))
	catalog.validate_all()


def test_merge_into_existing_adds_renders(tmp_path: Path) -> None:
	# First write a base collection without render extension
	out = tmp_path / "merge-test"
	out.mkdir()
	base_coll = build_collection_from_directory(
		MAPS_DIR,
		TRAIT_METADATA,
		STAT_METADATA,
		include_render_extension=False,
	)
	save_collection(base_coll, out)

	# Now build with render extension enabled and save with overwrite_items=False
	with_render = build_collection_from_directory(
		MAPS_DIR,
		TRAIT_METADATA,
		STAT_METADATA,
		include_render_extension=True,
	)
	save_collection(with_render, out, overwrite_items=False, additional_items=list(with_render.get_items()))

	# Verify item JSON now contains the render extension and renders
	item_path = next((out / "items").glob("*.json"))
	with item_path.open("r", encoding="utf-8") as fh:
		item = json.load(fh)

	assert RENDER_EXTENSION in item.get("stac_extensions", [])
	assert "renders" in (item.get("properties") or {})