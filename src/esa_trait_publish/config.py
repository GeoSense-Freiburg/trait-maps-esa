"""Simple, static configuration for the STAC publishing scaffold.

This module is intentionally lightweight: it exposes a small dictionary with
collection-level metadata, a media type constant for COG/GeoTIFF assets, and
a couple of convenience defaults used across the project.
"""

from typing import Dict, List


COLLECTION_CONFIG: Dict[str, object] = {
	"id": "global-plant-trait-maps",
	"title": "Global Plant Trait Maps (ESA scaffold)",
	"description": (
		"Global plant functional trait maps (31 traits), 1 km resolution, global extent. "
		"Derived from GBIF, sPlot, TRY and Earth observation data. "
		"Dataset hosted on Zenodo (DOI: 10.5281/zenodo.14646322)."
	),
	# Use a conservative placeholder license until the authoritative Zenodo
	# metadata is used. 
	"license": "CC BY 4.0", #  Creative Commons Attribution 4.0 International 
	"spatial_extent": [-180.0, -90.0, 180.0, 90.0],
	# DOI landing page for describedby link
	"zenodo_doi_url": "https://doi.org/10.5281/zenodo.14646322",
}


COG_MEDIA_TYPE: str = "image/tiff; application=geotiff; profile=cloud-optimized"


DEFAULT_FILE_EXTENSIONS: List[str] = [".tif", ".tiff"]

# Base href used to build hosted asset URLs for publication. TODO: change to PRR lateer when published
ASSET_BASE_HREF: str = "https://zenodo.org/records/14646322/files/"

# Explicit Zenodo files base URL for the published dataset. Use this to
# construct hosted file URLs for STAC asset hrefs in the form:
#   https://zenodo.org/records/14646322/files/{filename}
# Keep this constant simple (no API calls). Replace if another host/record
# is used.
ZENODO_FILE_BASE_URL: str = "https://zenodo.org/records/14646322/files"


def get_collection_config() -> Dict[str, object]:
	"""Return a shallow copy of the collection config.

	Keeping the copy shallow is sufficient because values are primitives or
	small lists.
	"""
	return dict(COLLECTION_CONFIG)

