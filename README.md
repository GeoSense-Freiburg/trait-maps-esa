# QIUICK START RUNNING CODE

`bash
source .venv/bin/activate
python scripts/build_stac.py \
  --maps-dir data/global_trait_maps \
  --trait-metadata metadata/trait_mapping.json \
  --stat-metadata metadata/trait_stat_mapping.json \
  --output-dir outputs/stac_maps
`
# Global Plant Trait Maps – STAC Preparation for ESA EarthCODE / APEx

## Overview

This repository provides a pipeline to generate **STAC-compliant metadata** for global plant trait maps, enabling publication via the ESA EarthCODE Open Science Catalog and subsequent integration into ESA APEx.

The underlying dataset is publicly available on Zenodo:
[https://zenodo.org/records/14646322](https://zenodo.org/records/14646322)
DOI: [https://doi.org/10.5281/zenodo.14646322](https://doi.org/10.5281/zenodo.14646322)

The dataset comprises 31 global plant functional trait maps (1 km resolution), derived from biodiversity observations (GBIF, sPlot, TRY) and modeled using Earth observation data.

---

## Objective

The goal is to transform raster prediction outputs into a structured geospatial data product that is:

* compliant with STAC
* compatible with ESA EarthCODE Open Science Catalog
* suitable for visualization in ESA APEx

Relevant documentation:

* EarthCODE contribution guidelines:
  [https://esa-earthcode.github.io/documentation/Technical%20Documentation/Open%20Science%20Catalog/Contributing%20to%20the%20Open%20Science%20Catalog](https://esa-earthcode.github.io/documentation/Technical%20Documentation/Open%20Science%20Catalog/Contributing%20to%20the%20Open%20Science%20Catalog)

* OSC STAC extension:
  [https://github.com/stac-extensions/osc](https://github.com/stac-extensions/osc)

---

## Scope

This repository currently focuses on:

* global trait map rasters (Cloud Optimized GeoTIFFs assumed)
* generation of a STAC product collection

The training dataset is not yet included.

---

## Repository Structure

```
project_root/
├── data/
│   ├── global_trait_maps/
│   └── training_data/
├── metadata/
│   ├── trait_mapping.json
│   └── trait_stat_mapping.json
├── src/esa_trait_publish/
├── scripts/build_stac.py
├── outputs/stac_maps/
├── README.md
└── pyproject.toml
```

---

## Input Data

### Raster data

* Format: Cloud Optimized GeoTIFF (COG)
* Global extent
* Consistent CRS

### Metadata

* `trait_mapping.json`: trait ID → name, description, unit
* `trait_stat_mapping.json`: statistic ID → statistic type (e.g. mean, std)

These files are used to enrich STAC item properties.

---

## Functionality

The pipeline:

1. scans raster files in `data/global_trait_maps/`
2. parses filenames to extract trait and statistic identifiers
3. reads raster metadata (extent, CRS, nodata, dimensions)
4. merges raster metadata with external trait metadata
5. generates:

   * one STAC Collection
   * one STAC Item per raster (or trait-stat combination)
6. writes outputs to `outputs/stac_maps/`

---

## Usage

```
python scripts/build_stac.py \
  --maps-dir data/global_trait_maps \
  --trait-metadata metadata/trait_mapping.json \
  --stat-metadata metadata/trait_stat_mapping.json \
  --output-dir outputs/stac_maps
```

---

## STAC Design

* **Collection**: global plant trait maps (product-level)
* **Items**: individual raster products
* **Assets**: links to raster files (COGs)

The implementation is designed to be compatible with OSC STAC requirements and extendable to include additional metadata fields.

