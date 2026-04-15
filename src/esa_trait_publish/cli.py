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

	collection = build_collection_from_directory(maps_dir, trait_metadata, stat_metadata)
	save_collection(collection, output_dir)

	print(f"Saved collection to: {output_dir}")
	print(f"Items in collection: {len(list(collection.get_items()))}")


if __name__ == "__main__":
	main()

