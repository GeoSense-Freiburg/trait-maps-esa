import GeoTIFF from "ol/source/GeoTIFF.js";
import WebGLTileLayer from "ol/layer/WebGLTile.js";
import LayerGroup from "ol/layer/Group.js";
import VectorLayer from "ol/layer/Vector.js";
import { get as getProjection, transformExtent } from "ol/proj.js";
import proj4 from "proj4";
import { register } from "ol/proj/proj4.js";
import { installNativeAoACrossShader } from "./NativeAoACrossShader";
import { getCovContourSource } from "./CovContours";
import {
  assetVersionFor,
  getOrCreateDerivedResource,
  incrementDerivedCounter,
  stableDerivedKey,
} from "./DerivedVisualizationCache";
import { AOA_RENDERER_ALGORITHM_VERSION } from "./DerivedVisualizationConfig";

proj4.defs(
  "EPSG:6933",
  "+proj=cea +lat_ts=30 +lon_0=0 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs",
);
register(proj4);
const epsg6933 = getProjection("EPSG:6933");
epsg6933?.setExtent([
  -17367530.445161372, -7342230.205017054, 17367530.445161372,
  7342230.205017056,
]);
epsg6933?.setWorldExtent([-180, -86, 180, 86]);

const rgba = (hex, alpha = 1) => {
  const value = hex.replace("#", "");
  return [0, 2, 4]
    .map((index) => Number.parseInt(value.slice(index, index + 2), 16))
    .concat(alpha);
};

const rawValue = (physical, band) =>
  (physical - (band.offset ?? 0)) / (band.scale || 1);
const physicalValue = (raw, band) =>
  raw * (band.scale || 1) + (band.offset ?? 0);
const sourceCache = new Map();
const rasterDiagnosticsLogged = new Set();
const DEFAULT_MEAN_RAW_STOPS = [-32767, -10922, 10922, 32767];

const dataTypeRange = (band) => {
  const type = String(band.data_type ?? "").toLowerCase();
  if (type === "int16") return [-32768, 32767];
  if (type === "uint16") return [0, 65535];
  if (type === "int8") return [-128, 127];
  if (type === "uint8" || type === "byte") return [0, 255];
  if (type === "int32") return [-2147483648, 2147483647];
  if (type === "uint32") return [0, 4294967295];
  return [-Number.MAX_VALUE, Number.MAX_VALUE];
};

const validRawRange = (band) => {
  const [minimum, maximum] = dataTypeRange(band);
  return [
    band.nodata === minimum ? minimum + 1 : minimum,
    band.nodata === maximum ? maximum - 1 : maximum,
  ];
};

const validBandCondition = (band, bandIndex) => {
  const [minimum, maximum] = validRawRange(band);
  return [
    "all",
    [">", ["band", 4], 0],
    ["!=", ["band", bandIndex], band.nodata],
    [">=", ["band", bandIndex], minimum],
    ["<=", ["band", bandIndex], maximum],
  ];
};

const sourceFor = (product) => {
  if (sourceCache.has(product.browserHref))
    return sourceCache.get(product.browserHref);
  const started = performance.now();
  const source = new GeoTIFF({
    normalize: false,
    interpolate: false,
    transition: 0,
    // Zenodo rate-limits large numbers of tiny range requests. GeoTIFF.js only
    // coalesces them when blockSize is explicit; 1 MiB also comfortably covers
    // the COG's small metadata ranges and keeps the cache bounded to 64 MiB.
    sourceOptions: {
      blockSize: 1024 * 1024,
      cacheSize: 64,
    },
    sources: [{ url: product.browserHref, nodata: product.nodata }],
  });
  if (import.meta.env.DEV) {
    source.once("change", () =>
      console.debug(
        `[plant-traits] raster source initialized in ${(
          performance.now() - started
        ).toFixed(0)} ms`,
        product.browserHref,
      ),
    );
  }
  sourceCache.set(product.browserHref, source);
  // Retain recently viewed traits without allowing the remote tile caches to
  // grow without bound during long exploration sessions.
  if (sourceCache.size > 4) sourceCache.delete(sourceCache.keys().next().value);
  return source;
};

const logRasterDiagnostics = (item, source) => {
  if (!import.meta.env.DEV || rasterDiagnosticsLogged.has(item.id)) return;
  const log = () => {
    if (source.getState() !== "ready" || rasterDiagnosticsLogged.has(item.id))
      return;
    source.un("change", log);
    rasterDiagnosticsLogged.add(item.id);
    const band = item.products.mean;
    const [minimum, maximum] = validRawRange(band);
    console.debug("[plant-traits] mean raster validity", {
      item: item.id,
      nodata: band.nodata,
      scale: band.scale ?? 1,
      offset: band.offset ?? 0,
      rawValidRange: [minimum, maximum],
      scaledValidRange: [
        physicalValue(minimum, band),
        physicalValue(maximum, band),
      ],
      alphaBand: source.bandCount > 3 ? 4 : null,
      usesMaskOrAlphaBand: source.bandCount > 3,
    });
  };
  if (source.getState() === "ready") log();
  else source.on("change", log);
};

const meanStyle = (band, style, sampledStops = null) => {
  const rawStops = sampledStops ?? DEFAULT_MEAN_RAW_STOPS;
  return {
    color: [
      "case",
      validBandCondition(band, 1),
      [
        "interpolate",
        ["linear"],
        ["band", 1],
        ...rawStops.flatMap((value, index) => [
          value,
          rgba(style.palette[index]),
        ]),
      ],
      [0, 0, 0, 0],
    ],
  };
};

const covStyle = (band, style) => ({
  color: [
    "case",
    validBandCondition(band, 2),
    [
      "interpolate",
      ["linear"],
      ["band", 2],
      ...style.domain.flatMap((value, index) => [
        rawValue(value, band),
        rgba(style.palette[index]),
      ]),
    ],
    [0, 0, 0, 0],
  ],
});

const quantile = (sorted, probability) => {
  const position = (sorted.length - 1) * probability;
  const lower = Math.floor(position);
  const fraction = position - lower;
  return (
    sorted[lower] +
    (sorted[Math.min(lower + 1, sorted.length - 1)] - sorted[lower]) * fraction
  );
};

export const sampleMeanStyle = (layer, map, item, style) => {
  const values = [];
  const size = map.getSize();
  if (!size) return null;
  // GPU readback is comparatively expensive; this coarse screen sample is
  // sufficient for robust display quantiles without stalling interaction.
  for (let y = 24; y < size[1]; y += 48) {
    for (let x = 24; x < size[0]; x += 48) {
      const pixel = layer.getData([x, y]);
      const value = pixel?.[0];
      const alpha = pixel?.length > 3 ? pixel.at(-1) : 255;
      const [minimum, maximum] = validRawRange(item.products.mean);
      if (
        Number.isFinite(value) &&
        alpha > 0 &&
        value !== item.products.mean.nodata &&
        value >= minimum &&
        value <= maximum
      ) {
        values.push(value);
      }
    }
  }
  if (values.length < 20) return null;
  values.sort((left, right) => left - right);
  const rawStops = [0.05, 0.35, 0.65, 0.95].map((probability) =>
    quantile(values, probability),
  );
  if (new Set(rawStops.map((value) => value.toFixed(6))).size < 2) return null;
  layer.setStyle(meanStyle(item.products.mean, style, rawStops));
  return rawStops.map((value) => physicalValue(value, item.products.mean));
};

export const createPlantTraitLayerGroup = (
  item,
  visualization,
  mapProjection = "EPSG:3857",
) => {
  const assetVersion = assetVersionFor(item, item.products.mean);
  const layerCacheKey = stableDerivedKey("plant-trait-layer-group", {
    itemId: item.id,
    assetHref: item.products.mean.canonicalHref,
    assetVersion,
    mapProjection,
    algorithmVersion: AOA_RENDERER_ALGORITHM_VERSION,
  });
  return getOrCreateDerivedResource(layerCacheKey, () => {
    // Mean, CoV and AoA are bands in one canonical TIFF. Sharing one source
    // avoids three metadata parses, tile caches and sets of Zenodo range calls.
    const sharedSource = sourceFor(item.products.mean);
    logRasterDiagnostics(item, sharedSource);
    const mean = new WebGLTileLayer({
      source: sharedSource,
      style: meanStyle(item.products.mean, visualization.resolvedStyles.mean),
    });
    mean.set("title", `${item.title} mean`);
    mean.set("canonicalAssetHref", item.products.mean.canonicalHref);

    const cov = new WebGLTileLayer({
      source: sharedSource,
      style: covStyle(item.products.cov, visualization.resolvedStyles.cov),
      visible: false,
      opacity: visualization.resolvedStyles.cov.opacity,
    });
    cov.set("title", "CoV coloured overlay");
    cov.set("canonicalAssetHref", item.products.cov.canonicalHref);

    const covContours = new VectorLayer({
      source: getCovContourSource(item, mapProjection),
      visible: false,
      opacity: visualization.resolvedStyles.cov.opacity,
      declutter: false,
      updateWhileAnimating: false,
      updateWhileInteracting: false,
    });
    covContours.set("title", "CoV Contour lines");
    covContours.set("canonicalAssetHref", item.products.cov.canonicalHref);

    const aoa = new WebGLTileLayer({
      source: sharedSource,
      style: { color: [0, 0, 0, 0] },
      visible: true,
      opacity: 1,
    });
    aoa.set("title", "AoA native cross mask — outside");
    aoa.set("canonicalAssetHref", item.products.aoa.canonicalHref);
    const projection = item.properties ?? {};
    const aoaStarted = performance.now();
    const aoaInstalled = installNativeAoACrossShader(
      aoa,
      {
        source_epsg: Number(String(projection["proj:code"]).split(":").at(-1)),
        source_extent: projection["proj:bbox"],
        shape: projection["proj:shape"],
        map_epsg: Number(String(mapProjection).split(":").at(-1)),
      },
      {
        cross_color: visualization.resolvedStyles.aoa.crossColor,
        cross_alpha: visualization.resolvedStyles.aoa.crossAlpha,
      },
    );
    if (aoaInstalled) {
      const aoaCacheKey = stableDerivedKey("aoa-renderer", {
        itemId: item.id,
        assetHref: item.products.aoa.canonicalHref,
        assetVersion,
        band: item.products.aoa.band,
        mapProjection,
        algorithmVersion: AOA_RENDERER_ALGORITHM_VERSION,
      });
      incrementDerivedCounter(aoaCacheKey, "aoaGenerationCount");
    }
    if (import.meta.env.DEV) {
      console.debug(
        `[plant-traits] AoA renderer initialized in ${(
          performance.now() - aoaStarted
        ).toFixed(1)} ms`,
      );
    }

    const group = new LayerGroup({ layers: [mean, cov, covContours, aoa] });
    // eox-map's attribution collector calls this on every top-level map layer;
    // OpenLayers LayerGroup does not implement it itself.
    group.getAttributions = () => [];
    group.set("title", "Canonical STAC plant-trait layers");
    group.set("canonicalItemUrl", item.canonicalItemUrl);
    return { group, mean, cov, covContours, aoa };
  });
};

export const fitItem = (map, item) => {
  const mapProjection = map.getView().getProjection().getCode();
  const itemProjection = item.properties?.["proj:code"];
  const nativeExtent = item.properties?.["proj:bbox"];
  if (mapProjection === itemProjection && nativeExtent) {
    map.getView().fit(nativeExtent, {
      size: map.getSize(),
      padding: [30, 30, 30, 30],
      maxZoom: 5,
    });
    return;
  }
  if (!item.bbox) return;
  const extent = transformExtent(
    item.bbox,
    "EPSG:4326",
    map.getView().getProjection(),
  );
  map.getView().fit(extent, {
    size: map.getSize(),
    padding: [30, 30, 30, 30],
    maxZoom: 5,
  });
};

export const formatMeanStops = (item) =>
  DEFAULT_MEAN_RAW_STOPS.map((raw) => physicalValue(raw, item.products.mean));

const readPhysicalBandValue = (raw, alpha, band) => {
  const [minimum, maximum] = validRawRange(band);
  if (
    !Number.isFinite(raw) ||
    alpha <= 0 ||
    raw === band.nodata ||
    raw < minimum ||
    raw > maximum
  ) {
    return null;
  }
  return physicalValue(raw, band);
};

export const readPlantTraitValuesAtPixel = (layer, pixel, item) => {
  const values = layer.getData(pixel);
  const alpha = values?.length > 3 ? values[3] : 255;
  return {
    mean: readPhysicalBandValue(values?.[0], alpha, item.products.mean),
    cov: readPhysicalBandValue(values?.[1], alpha, item.products.cov),
    aoa: readPhysicalBandValue(values?.[2], alpha, item.products.aoa),
  };
};
