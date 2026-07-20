import Feature from "ol/Feature.js";
import LineString from "ol/geom/LineString.js";
import VectorSource from "ol/source/Vector.js";
import { transform } from "ol/proj.js";
import Style from "ol/style/Style.js";
import Stroke from "ol/style/Stroke.js";
import Text from "ol/style/Text.js";
import Fill from "ol/style/Fill.js";
import { COV_CONTOUR_LEVELS, covColorForValue } from "./CovPalette";
import {
  assetVersionFor,
  getOrCreateDerivedResource,
  getOrCreateDerivedResult,
  getOrCreateRasterData,
  incrementDerivedCounter,
  stableDerivedKey,
} from "./DerivedVisualizationCache";
import {
  COV_CONTOUR_ALGORITHM_VERSION,
  COV_CONTOUR_OVERVIEW_FACTOR,
  COV_CONTOUR_OVERVIEW_INDEX,
  RASTER_DECODE_ALGORITHM_VERSION,
} from "./DerivedVisualizationConfig";

const labelledStyleCache = new Map();
const lineStyleCache = new Map();

const relativeLuminance = (hex) => {
  const channels = [1, 3, 5].map(
    (index) => Number.parseInt(hex.slice(index, index + 2), 16) / 255,
  );
  const [red, green, blue] = channels.map((channel) =>
    channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4,
  );
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
};

const runWorkerJob = (message, onProgress) =>
  new Promise((resolve, reject) => {
    const worker = new Worker(
      new URL("./CovContourWorker.js", import.meta.url),
      { type: "module" },
    );
    let settled = false;
    const finish = (callback, value) => {
      if (settled) return;
      settled = true;
      worker.onmessage = null;
      worker.onerror = null;
      worker.terminate();
      callback(value);
    };
    worker.onmessage = ({ data }) => {
      if (data.type === "progress") onProgress?.(data.done, data.total);
      if (data.type === "complete") finish(resolve, data.result);
      if (data.type === "error") finish(reject, new Error(data.message));
    };
    worker.onerror = (error) => finish(reject, error);
    worker.postMessage(message);
  });

const covRasterCacheKey = (item) =>
  stableDerivedKey("raster", {
    itemId: item.id,
    assetHref: item.products.cov.canonicalHref,
    assetVersion: assetVersionFor(item, item.products.cov),
    bands: [
      item.products.mean.band,
      item.products.cov.band,
      item.products.aoa.band,
    ],
    overviewIndex: COV_CONTOUR_OVERVIEW_INDEX,
    overviewFactor: COV_CONTOUR_OVERVIEW_FACTOR,
    algorithmVersion: RASTER_DECODE_ALGORITHM_VERSION,
  });

const covContourCacheKey = (item, targetProjection) =>
  stableDerivedKey("cov-contours", {
    itemId: item.id,
    assetHref: item.products.cov.canonicalHref,
    assetVersion: assetVersionFor(item, item.products.cov),
    band: item.products.cov.band,
    overviewIndex: COV_CONTOUR_OVERVIEW_INDEX,
    overviewFactor: COV_CONTOUR_OVERVIEW_FACTOR,
    levels: COV_CONTOUR_LEVELS,
    targetProjection,
    algorithmVersion: COV_CONTOUR_ALGORITHM_VERSION,
  });

const loadFixedRaster = (item) => {
  const key = covRasterCacheKey(item);
  return getOrCreateRasterData(key, () => {
    incrementDerivedCounter(key, "workerJobCount");
    incrementDerivedCounter(key, "rasterFetchCount");
    incrementDerivedCounter(key, "rasterDecodeCount");
    return runWorkerJob({
      jobType: "decode-raster",
      item,
      overviewIndex: COV_CONTOUR_OVERVIEW_INDEX,
    });
  });
};

const generateContours = (item, targetProjection, onProgress) => {
  const key = covContourCacheKey(item, targetProjection);
  return getOrCreateDerivedResult(key, async () => {
    const raster = await loadFixedRaster(item);
    incrementDerivedCounter(key, "workerJobCount");
    incrementDerivedCounter(key, "contourGenerationCount");
    const generated = await runWorkerJob(
      {
        jobType: "generate-contours",
        raster,
        levels: COV_CONTOUR_LEVELS,
      },
      onProgress,
    );
    return {
      descriptors: generated.descriptors.map(({ level, coordinates }) => ({
        level,
        coordinates:
          targetProjection === "EPSG:6933"
            ? coordinates
            : coordinates.map((coordinate) =>
                transform(coordinate, "EPSG:6933", targetProjection),
              ),
      })),
      filterStats: generated.filterStats,
    };
  });
};

export const getCovContourSource = (item, targetProjection) => {
  const key = `${covContourCacheKey(
    item,
    targetProjection,
  )}|openlayers-vector-source`;
  return getOrCreateDerivedResource(
    key,
    () => new VectorSource({ wrapX: false }),
  );
};

const stylesFor = (level, label) => {
  const labelled = Boolean(label);
  const cache = labelled ? labelledStyleCache : lineStyleCache;
  if (cache.has(level)) return cache.get(level);
  const color = covColorForValue(level);
  const haloColor =
    level <= 0.03 ? "rgba(35,35,35,.72)" : "rgba(255,255,255,.82)";
  const styles = [
    new Style({ stroke: new Stroke({ color: haloColor, width: 3.4 }) }),
    new Style({ stroke: new Stroke({ color, width: 1.8 }) }),
  ];
  if (labelled) {
    const neutralHalo =
      relativeLuminance(color) > 0.45
        ? "rgba(20,28,32,.96)"
        : "rgba(255,255,255,.96)";
    const textOptions = {
      text: label,
      placement: "line",
      repeat: 400,
      overflow: false,
      keepUpright: true,
      maxAngle: Math.PI / 4,
      padding: [1, 2, 1, 2],
      font: "600 14px sans-serif",
    };
    styles.push(
      new Style({
        zIndex: 100,
        text: new Text({
          ...textOptions,
          fill: new Fill({ color: neutralHalo }),
          stroke: new Stroke({ color: neutralHalo, width: 4 }),
        }),
      }),
      new Style({
        zIndex: 101,
        text: new Text({
          ...textOptions,
          fill: new Fill({ color }),
        }),
      }),
    );
  }
  cache.set(level, styles);
  return styles;
};

const contourLayerStyle = (feature) =>
  stylesFor(
    feature.get("contourValue"),
    feature.get("labelEligible") ? feature.get("contourLabel") : null,
  );

export const populateCovContourLayer = async (
  layer,
  item,
  onProgress,
  targetProjection = "EPSG:3857",
) => {
  const cacheKey = covContourCacheKey(item, targetProjection);
  const source = layer.getSource();
  if (source.get("derivedCacheKey") === cacheKey) {
    layer.setStyle(contourLayerStyle);
    layer.set("contoursLoaded", true);
    return source.getFeatures().length;
  }
  const { descriptors, filterStats } = await generateContours(
    item,
    targetProjection,
    onProgress,
  );
  // Another requester may have populated the shared source while this caller
  // awaited the same in-flight Promise.
  if (source.get("derivedCacheKey") === cacheKey) {
    layer.setStyle(contourLayerStyle);
    layer.set("contoursLoaded", true);
    return source.getFeatures().length;
  }
  const features = descriptors.map(
    ({ level, coordinates }) =>
      new Feature({
        geometry: new LineString(coordinates),
        cov: level,
        contourValue: level,
        contourLabel: `${Math.round(level * 100)}%`,
        labelEligible: coordinates.length >= 16,
      }),
  );
  layer.setStyle(contourLayerStyle);
  source.addFeatures(features);
  source.set("derivedCacheKey", cacheKey);
  source.set("contourFilterStats", filterStats);
  layer.set("contoursLoaded", true);
  return features.length;
};
