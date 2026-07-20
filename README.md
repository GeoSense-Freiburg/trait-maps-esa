# EO Plant Traits Dashboard

This repository publishes the Global Plant Functional Trait Maps as a static
STAC catalog and an EO Dashboard viewer. Scientific raster assets remain on
Zenodo and are streamed as cloud-optimized GeoTIFFs; the repository contains
only metadata, viewer code, configuration, and lightweight reference data.

## Live viewer

GitHub Pages URL: _available after the first public deployment_.

## Main features

- Selection across all traits in the canonical STAC catalog
- Mean trait raster with dynamic legend and exact value inspection
- CoV uncertainty as a raster overlay or labelled contour lines
- Native-cell Area of Applicability warning crosses
- Client-side raster/derived-data caching and remote COG diagnostics
- Static deployment without copying production TIFF files into GitHub

## Local development

```bash
uv sync --extra dev
npm --prefix eodash/viewer ci
./scripts/check_eodash_setup.sh
./scripts/dev_eodash.sh
```

Open <http://localhost:3000/>. Run the viewer quality checks with:

```bash
npm --prefix eodash/viewer run lint
npm --prefix eodash/viewer run build
```

## Technical documentation

See [docs/viewer.md](docs/viewer.md) for architecture, data flow, maintenance,
deployment, and trait-onboarding details.
