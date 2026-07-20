# Viewer technical guide

## Repository structure

- `stac_catalogs/stac_catalog_v1/` — authoritative static STAC catalog,
  collection, and plant-trait items.
- `eodash/viewer/` — EO Dashboard application and OpenLayers integration.
- `eodash/config/` — generated asset inventory and the small band mapping used
  by the viewer.
- `eodash/styles/` — shared mean, CoV, and AoA visualization settings.
- `eodash/reference/` — lightweight Natural Earth reference boundaries.
- `scripts/` — STAC generation, validation, inventory, link checking, and local
  development commands.
- `src/esa_trait_publish/` — Python package for publishing scientific STAC
  metadata.
- `.github/workflows/deploy-eodash-pages.yml` — static GitHub Pages build.

The canonical catalog is described in more detail in
[eodash-stac-audit.md](eodash-stac-audit.md).

## Viewer architecture

`src/main.js` initializes EO Dashboard with the canonical catalog endpoint and
registers the dashboard templates. `PlantTraitControls.js` owns trait
selection, visibility and opacity controls, legends, hover readout, and lazy
contour activation. `canonicalCatalog.js` traverses the catalog and resolves a
selected item into its mean, CoV, and AoA products. `PlantTraitMapLayers.js`
creates the OpenLayers layer group.

The map uses EPSG:6933, matching the scientific rasters. This avoids
reprojecting raster pixels and the native AoA grid. The current reference map
is the lightweight Natural Earth layer installed by `PlantTraitBasemap.js`.

## STAC workflow

`stac_catalogs/stac_catalog_v1/catalog.json` is the metadata authority. Its
relative links lead to one collection and the item documents; absolute asset
links continue to point at Zenodo. Viewer components never hardcode individual
Zenodo asset URLs.

Each item has one `data` asset with three explicitly named `raster:bands`:

1. `trait_mean`
2. `coefficient_of_variation`
3. `area_of_applicability`

`eodash/config/asset-inventory.json` is a generated index for fast selector
startup, not a second scientific catalog. Regenerate it after changing the
canonical catalog:

```bash
python scripts/build_eodash_asset_inventory.py
./scripts/check_eodash_setup.sh
```

`plant-trait-visualization.json` maps the three product names to their asset
key and band number. Shared presentation settings live in `eodash/styles/`;
there are no per-trait style files.

## Raster loading

The canonical Zenodo URL is preserved in STAC. Because the normal Zenodo file
response does not expose browser CORS headers, `canonicalCatalog.js` derives
Zenodo's API content URL for browser access to the same published object.

Mean, CoV, and AoA share one OpenLayers `GeoTIFF` source and tile cache.
Normalization and interpolation are disabled so styles and hover inspection
receive raw Int16 samples. Per-band NoData, scale, and offset come from
`raster:bands`. A 1 MiB request block size coalesces small range reads, and the
source cache retains at most four recently selected traits.

Use `/?debug=remote-cog` to isolate remote COG/OpenLayers access from the EO
Dashboard integration. `scripts/validate_stac_raster_assets.py` validates HTTP
ranges, CORS, georeferencing, TIFF structure, blocks, and overviews without
downloading complete assets by default.

## Caching

`DerivedVisualizationCache.js` maintains separate in-memory caches for decoded
raster data, derived arrays/geometries, and OpenLayers resources. In-flight
Promises are shared, so simultaneous requests for the same derivation launch
one calculation.

Keys include the item, canonical asset URL, asset version/checksum, band,
fixed overview, derivation parameters, target projection, and algorithm
version. Development counters expose fetch, decode, worker, contour, AoA, hit,
and miss counts through `window.__EODASH_DERIVED_CACHE__.snapshot()`.

The cache is intentionally session-only. Zooming, panning, opacity changes,
visibility changes, and label placement reuse the same vector source and
features.

## Contour generation

CoV contours are optional and generated only when contour mode is first
selected. `CovContourWorker.js` reads overview index 4 (factor 16), applies
band scale/offset and the common validity mask, then runs Marching Squares at
fixed levels 2%, 3%, 4%, 6%, 8%, and 12%.

The worker assembles line strings and conservatively rejects only tiny acute
three-point fragments adjacent to NoData. `CovContours.js` transforms the
completed coordinates only when the map projection differs, creates one
cached vector source, and applies cached line/label styles. Labels use each
feature's existing contour level; rendering never samples the raster again.

## Area of Applicability

AoA is band 3 of the same COG. Its metadata and viewer mapping define `0` as
inside and `1` as outside. `NativeAoACrossShader.js` draws an orange cross in
each resolvable outside cell while leaving inside cells transparent. The shader
uses the raster's native EPSG:6933 extent and shape, so it does not generate or
move vector features during interaction.

## Hover system

Pointer updates are coalesced with `requestAnimationFrame`. One
`layer.getData(pixel)` call returns mean, CoV, AoA, and alpha for the same map
position. Each band is checked independently for alpha, NoData, finite values,
and its raw data-type range before scale and offset are applied.

The readout formats the mean with its trait unit, CoV as a percentage of the
configured fraction, and binary AoA as `Inside AoA` or `Outside AoA`. The same
pointer coordinate is transformed from EPSG:6933 to WGS84 for latitude and
longitude. Hovering does not launch workers, full-raster reads, or contour
generation.

## Legends

The trait colorbar uses the exact physical stops supplied to the rendered mean
style. It starts from the default scaled Int16 stops and updates to the current
screen's valid 5–95% sample when available. The gradient preserves the actual
nonuniform stop positions.

CoV raster mode uses the same palette and domain as the WebGL raster style.
Contour mode replaces it with a discrete key using `CovPalette.js`; hiding CoV
hides the key. The AoA legend follows AoA visibility and describes both binary
states. Compact keyboard-accessible help popovers provide interpretation text.

## Deployment workflow

Pushes to `eo-dashboard` trigger the Pages workflow. The workflow installs
viewer dependencies, computes the Vite base from repository metadata or
`EODASH_BASE_PATH`, and runs the production build. The artifact contains the
built viewer, canonical STAC tree, configuration, shared styles, and the
Natural Earth reference map. It explicitly fails if a TIFF is present.

Production endpoints are relative to `import.meta.env.BASE_URL`, supporting
both root Pages sites and `/REPOSITORY/` project sites without a hardcoded
owner. Deployment does not rebuild or copy scientific raster assets.

## Adding a new trait

1. Publish a browser-readable three-band COG externally. Keep its scientific
   values, georeferencing, NoData, scale, and offset authoritative.
2. Add the item to the canonical collection using the existing STAC publishing
   workflow. Band names must match the three names above.
3. Keep the asset href absolute HTTPS and ensure HTTP range requests and CORS
   work. Do not commit the TIFF.
4. Regenerate `eodash/config/asset-inventory.json`.
5. Run:

   ```bash
   python scripts/check_static_stac_links.py
   python scripts/validate_stac_raster_assets.py --sample 1
   ./scripts/check_eodash_setup.sh
   npm --prefix eodash/viewer run lint
   npm --prefix eodash/viewer run build
   ```

No viewer component or per-trait style should be necessary when the item uses
the established asset and band metadata.

## Known limitations

- The generated inventory must be refreshed when canonical item links change.
- Zenodo API availability, CORS policy, and rate limiting affect interactive
  raster loading.
- Derived caches are in-memory only and are lost on page reload.
- Global contours intentionally use the factor-16 overview and are an
  orientation layer; the CoV raster is the detailed source.
- Very dense global vector contours remain expensive to draw on low-powered
  devices even though they are generated only once.
- Native 1 km AoA crosses cannot be resolved when a cell is smaller than a few
  screen pixels.
- Automated end-to-end browser coverage is not yet part of CI.
