"""Command line interface for building the STAC collection.

This module provides a minimal argparse-based CLI that builds a STAC
collection from a directory of raster maps and saves it to an output
directory.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from .stac_builder import build_collection_from_directory, save_collection
from .stac_builder import (
	infer_product_status_from_path,
	load_existing_collection,
	merge_items_into_collection,
)


def build_parser() -> argparse.ArgumentParser:
	"""Create and return the command-line argument parser."""
	p = argparse.ArgumentParser(
		prog="build_stac",
		description="Build a STAC collection from global trait map rasters",
	)
	p.add_argument(
		"--maps-dir",
		required=True,
		help="Directory containing raster maps (tif/tiff)",
	)
	p.add_argument(
		"--trait-metadata",
		required=True,
		help="Path to metadata/trait_mapping.json",
	)
	p.add_argument(
		"--stat-metadata",
		required=True,
		help="Path to metadata/trait_stat_mapping.json",
	)
	p.add_argument(
		"--output-dir",
		required=True,
		help="Directory to write the STAC collection to",
	)

	p.add_argument(
		"--allow-unknown-status",
		action="store_true",
		help="Allow unknown product status and use 'unknown' instead of failing",
	)

	p.add_argument(
		"--preserve-existing-items",
		action="store_true",
		help="Do not overwrite existing item JSON files; only add new items",
	)
	p.add_argument(
		"--write-earthcode-registry",
		action="store_true",
		help="Also write a lightweight EarthCODE/Open Science Catalog registry collection",
	)
	p.add_argument(
		"--earthcode-registry-output-dir",
		required=False,
		help="Directory to write the EarthCODE registry collection to (overrides config)",
	)
	p.add_argument(
		"--full-stac-catalog-url",
		required=False,
		help="Public URL of the full hosted STAC catalog (used in registry child link)",
	)
	return p


def main(argv: Optional[list[str]] = None) -> None:
	"""Parse args, build the collection, and save it.

	Args:
		argv: optional list of arguments (for testing); if None, uses sys.argv
	"""
	parser = build_parser()
	args = parser.parse_args(argv)

	maps_dir = Path(args.maps_dir)
	trait_metadata = Path(args.trait_metadata)
	stat_metadata = Path(args.stat_metadata)
	output_dir = Path(args.output_dir)

	# infer status and attach to items created from this run
	try:
		status = infer_product_status_from_path(maps_dir)
	except ValueError:
		if args.allow_unknown_status:
			status = "unknown"
		else:
			raise

	new_collection = build_collection_from_directory(maps_dir, trait_metadata, stat_metadata)

	# attach product_status to each item
	for it in new_collection.get_items():
		it.properties = it.properties or {}
		it.properties.setdefault("trait_map:product_status", status)

	# if an existing collection exists, load and merge
	existing = load_existing_collection(output_dir)
	if existing is not None:
		existing_coll, existing_ids = existing
		# merge items (skip duplicates); pass existing_ids to avoid resolving items
		merged = merge_items_into_collection(
			existing_coll,
			list(new_collection.get_items()),
			preserve_existing=args.preserve_existing_items,
			status=status,
			existing_ids=existing_ids,
		)
		# save merged collection without overwriting existing item files when requested
		written = save_collection(
			merged,
			output_dir,
			overwrite_items=not args.preserve_existing_items,
			additional_items=list(new_collection.get_items()),
			write_earthcode_registry=args.write_earthcode_registry,
			earthcode_registry_output_dir=Path(args.earthcode_registry_output_dir) if args.earthcode_registry_output_dir else None,
			full_stac_catalog_url=args.full_stac_catalog_url,
		)
	else:
		written = save_collection(
			new_collection,
			output_dir,
			overwrite_items=not args.preserve_existing_items,
			additional_items=list(new_collection.get_items()),
			write_earthcode_registry=args.write_earthcode_registry,
			earthcode_registry_output_dir=Path(args.earthcode_registry_output_dir) if args.earthcode_registry_output_dir else None,
			full_stac_catalog_url=args.full_stac_catalog_url,
		)

	print(f"Saved collection to: {output_dir}")
	print(f"Items written: {written}")


if __name__ == "__main__":
	main()

