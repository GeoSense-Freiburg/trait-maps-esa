# Global Plant Trait Maps – STAC Generation for ESA EarthCODE

This repository generates STAC metadata for the *Global Plant Functional Trait Maps* dataset to support publication via the ESA EarthCODE Open Science Catalog and visualization in ESA APEx.

Dataset DOI:  
https://doi.org/10.5281/zenodo.14646322

The dataset contains 31 global plant functional trait maps at 1 km resolution derived from GBIF, sPlot, TRY, and Earth observation data.

---

## Quick Start

Recreate the environment with `uv`:

```bash
uv sync
source .venv/bin/activate
```

Generate or extend the STAC catalog:

```bash
python scripts/build_stac.py \
  --maps-dir data/global_trait_maps/analysis-ready \
  --trait-metadata metadata/trait_mapping.json \
  --stat-metadata metadata/trait_stat_mapping.json \
  --output-dir outputs/stac_maps
```

Run again with another input directory to extend the same collection:

```bash
python scripts/build_stac.py \
  --maps-dir data/global_trait_maps/experimental \
  --trait-metadata metadata/trait_mapping.json \
  --stat-metadata metadata/trait_stat_mapping.json \
  --output-dir outputs/stac_maps
```

Existing collections are extended rather than overwritten. The input folder name is written to each item as:

```json
"trait_map:product_status": "analysis-ready"
```

for example `analysis-ready` or `experimental`.

Files under:

```text
outputs/earthcode-registry/
```

are static EarthCODE registry metadata files. They act as catalog pointers to the hosted STAC catalog, not as the full item-level STAC catalog itself.

---

## Repository Structure

```text
project_root/
├── data/
│   ├── global_trait_maps/
│   │   ├── analysis-ready/
│   │   └── experimental/
        └── .../
├── metadata/
│   ├── trait_mapping.json
│   └── trait_stat_mapping.json
├── scripts/
│   └── build_stac.py
├── src/esa_trait_publish/
    ├── config.py # main hyperparameters
    ├── stac_builder.py # main functionality
    ├── ...
├── outputs/
│   ├── stac_maps/
│   └── earthcode-registry/
├── tests/
├── README.md
└── pyproject.toml
```

---

## Functionality

The pipeline:

1. scans raster files
2. extracts trait and statistic identifiers from filenames
3. reads raster metadata (extent, CRS, nodata, dimensions, bands)
4. merges raster and trait metadata
5. generates:
   - a STAC catalog
   - a STAC collection
   - one STAC item per raster product

Outputs are written to the specified output directory.

---

## Output Structure

The generated catalog follows a standard STAC layout:

```text
<output-dir>/
├── catalog.json
├── collection.json
└── items/
    ├── <item>.json
    └── ...
```

- `catalog.json` — STAC catalog root
- `collection.json` — product-level metadata
- `items/*.json` — raster-level metadata and assets

---

## Standards and References

- EarthCODE contribution guidelines:  
  https://esa-earthcode.github.io/documentation/Technical%20Documentation/Open%20Science%20Catalog/Contributing%20to%20the%20Open%20Science%20Catalog

- OSC STAC extension:  
  https://github.com/stac-extensions/osc

- STAC specification:  
  https://stacspec.org/

---

## Notes

The implementation is compatible with ESA EarthCODE OSC requirements and can be extended with additional metadata fields, products, and processing levels.

