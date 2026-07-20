# EO Dashboard canonical STAC audit

Audit target: `stac_catalogs/stac_catalog_v1/catalog.json`. No scientific
metadata or asset URL was changed during this audit.

## Hierarchy

- Root: STAC `Catalog`, version `1.1.0`, id
  `global-plant-trait-maps-catalog`.
- Child: one STAC `Collection`, id `global-plant-trait-maps`.
- Items: 37 STAC `Feature` items in `items/`. Item ids equal their TIFF base
  names, from `X1080_mean_Shrub_Tree_Grass_1km` through the other trait ids.
- Internal catalog, collection and item links are relative. The link checker
  resolved 191 local links across 39 documents. The collection's publication,
  DOI and documentation links are absolute HTTPS links.
- Every raster asset URL is an absolute HTTPS Zenodo URL. Moving the JSON tree
  below a GitHub Pages project path therefore preserves both metadata and asset
  resolution.

The collection description says “31 traits”, while the collection contains 37
item links and 37 item files. This report records the discrepancy but does not
change that scientific/collection metadata.

## Items and assets

All 37 items use:

- asset key `data`;
- media type `image/tiff; application=geotiff; profile=cloud-optimized`;
- role `data`;
- one three-band TIFF per trait;
- WGS84 bbox `[-180, -65.47703940221221, 180, 90]` and matching Polygon
  geometry;
- Projection Extension v2 and Raster Extension v1.1.

Product identity is explicit in `raster:bands`, not inferred silently:

1. `trait_mean` — trait mean, with trait-specific unit, scale and offset;
2. `coefficient_of_variation` — CoV, with scale and offset;
3. `area_of_applicability` — binary AoA mask. Leaf Length explicitly documents
   `0 = inside, 1 = outside`; the other items name the same mask but generally
   omit that value explanation.

Items report `proj:code = EPSG:6933`, projected bbox, affine transform and
shape `[14682, 34734]`. Raster bands report `int16`, nodata `-32768`, scale,
offset and overview factors `[2, 4, 8, 16, 32]`. There is no STAC Render
Extension, no `renders` object, and no item/collection style link. Small
viewer-side style/config JSON is therefore required, while the canonical
scientific items remain unchanged.

The complete machine-readable mapping is generated from this catalog at
`eodash/config/asset-inventory.json`. Every item maps mean, CoV and AoA to the
real `data` asset and band indexes 1, 2 and 3.

## Installed EO Dashboard capability

The installed package is `@eodash/eodash 5.7.1`. Its source confirms:

- static root catalogs are loaded from their `links` array;
- relative links are resolved against the configured root endpoint;
- static collection `item` links are supported;
- HTTP `image/tiff` data assets create OpenLayers `GeoTIFF` WebGL layers;
- `style` links with `asset:keys` are supported, including collection fallback;
- client-supplied and STAC Render Extension presets are supported.

The canonical hierarchy is standards-compatible, but it models all traits as
same-date items in one collection. EO Dashboard's normal selector models
collections as indicators and items primarily as time steps, so its stock UI
cannot represent these 37 items as traits. The implementation consequently
keeps the canonical catalog as `stacEndpoint` and adds a thin viewer-side trait
adapter that discovers the collection/items and bands at runtime. It does not
copy item metadata or hardcode Zenodo file URLs.

## Remote raster evidence

`X1080_mean_Shrub_Tree_Grass_1km.tif` was checked remotely with a 16 KiB range
request and GDAL `/vsicurl/`:

- HTTP `206 Partial Content`, `Content-Range: bytes 0-16383/648486358`;
- TIFF signature present and `Accept-Ranges: bytes`;
- actual CRS EPSG:6933, size `34734 × 14682`, three Int16 bands;
- nodata `-32768`, declared band scale/offset values;
- 512 × 512 tiled blocks and five internal overviews;
- GeoTIFF image structure reports `LAYOUT=COG` and DEFLATE compression.

No TIFF rebuild is justified. The canonical Zenodo `/records/.../files/...`
response omits CORS, however. Zenodo's API content URL for the identical file
returns ranges and `Access-Control-Allow-Origin: *`, including a valid Range
preflight. The browser adapter derives that endpoint from the canonical href;
the committed STAC href is preserved. The API also enforces request-rate limits,
so Mean, CoV and AoA share one GeoTIFF source/tile cache. GeoTIFF.js uses a
bounded 1 MiB block cache to coalesce small reads. In a fresh direct OpenLayers
test of the initial Leaf Length item (`X144_mean_Shrub_Tree_Grass_1km`), the
source reached `ready` in EPSG:6933 and made 28 range requests during initial
rendering; all 28 returned 206 and none returned 429.

The full EO Dashboard test also rendered the canonical Leaf Length source. Its
runtime selector contained all 37 canonical items while startup fetched only
the selected item's JSON. Mean was visible, CoV was optional/off, AoA was
visible, and all three shared-source layers reported `ready`. A lazy CoV test
generated 27,313 contour paths from the 16× COG overview at fixed levels 2, 3,
4, 6, 8 and 12%; 3,551 sufficiently long paths received contour labels. The
common Mean/CoV/AoA validity mask contained 547,181 valid cells
(27.46% of that overview). These checks exercise the thin trait-selection
adapter; the canonical STAC remains EO Dashboard's configured `stacEndpoint`.
