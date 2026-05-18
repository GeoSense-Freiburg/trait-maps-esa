"""Simple, static configuration for the STAC publishing scaffold.

This module is intentionally lightweight: it exposes a small dictionary with
collection-level metadata, a media type constant for COG/GeoTIFF assets, and
a couple of convenience defaults used across the project.
"""

from typing import Dict, List


COLLECTION_CONFIG: Dict[str, object] = {
	"id": "global-plant-trait-maps",
	"title": "Global Plant Functional Trait Maps at 1 km Resolution",
	"description": (
		"Global plant functional trait maps (31 traits), 1 km resolution, global extent. "
		"Derived from GBIF, sPlot, TRY and Earth observation data. "
		"Dataset hosted on Zenodo (DOI: 10.5281/zenodo.14646322)."
	),
	"license": "CC-BY-4.0", #  Creative Commons Attribution 4.0 International (SPDX)
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
ZENODO_FILE_BASE_URL: str = "https://zenodo.org/records/14646322/files"


# STAC extension URLs and OSC project defaults
OSC_EXTENSION: str = "https://stac-extensions.github.io/osc/v1.0.0/schema.json"
PROJECTION_EXTENSION: str = "https://stac-extensions.github.io/projection/v2.0.0/schema.json"

# Scientific extension URL
SCIENTIFIC_EXTENSION: str = "https://stac-extensions.github.io/scientific/v1.0.0/schema.json"

# OSC defaults required by the user
OSC_TYPE: str = "product"
OSC_STATUS: str = "completed"
OSC_PROJECT: str = "FORTRACK"

# Dataset publication metadata (from Zenodo record)
DOI: str = "10.5281/zenodo.14646322"
DOI_URL: str = "https://doi.org/10.5281/zenodo.14646322"
SCIENTIFIC_CITATION: str = "Nature Communications, 17(1203), 2026"
PUBLISHED_DATE: str = "2026-01-30T00:00:00Z"

KEYWORDS = [
	"Plant traits",
	"Functional ecology",
	"Global maps",
	"1-km",
	"Citizen science",
	"Earth observation",
]

# Providers metadata (simple dicts; stac_builder will convert to pystac.Provider)
PROVIDERS = [
	{"name": "Zenodo", "roles": ["host"]},
	{"name": "Sensor-based Geoinformatics - University of Freiburg", "roles": ["producer", "processor"]},
]

# Configurable root href for catalogs. Defaults to the collection.json at the
# current directory. Can be updated later to point to a higher-level catalog
# or deployment root (multi-resolution catalogs, PRR/APEx root, etc.).
ROOT_HREF: str = "./collection.json"


def get_collection_config() -> Dict[str, object]:
	"""Return a shallow copy of the collection config.

	Keeping the copy shallow is sufficient because values are primitives or
	small lists.
	"""
	return dict(COLLECTION_CONFIG)

