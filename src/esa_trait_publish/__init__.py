"""esa_trait_publish package

Lightweight package initializer for the ESA trait STAC publishing scaffold.
This module intentionally contains no heavy logic. Implementation files live in
the sibling modules (config, raster_metadata, filename_parser, stac_builder).
"""

__all__ = [
    "config",
    "raster_metadata",
    "filename_parser",
    "stac_builder",
    "cli",
    "validate",
]
