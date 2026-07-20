import { fromUrl } from "geotiff";

const pointKey = ([x, y]) => `${x.toFixed(6)},${y.toFixed(6)}`;
const MAX_NODATA_FRAGMENT_LENGTH = 20000;
const MAX_NODATA_FRAGMENT_ANGLE = (15 * Math.PI) / 180;
const GRID_EPSILON = 1e-6;

const edgePoint = (edge, column, row, values, level) => {
  const [topLeft, topRight, bottomRight, bottomLeft] = values;
  const edgeValues = [
    [topLeft, topRight],
    [topRight, bottomRight],
    [bottomRight, bottomLeft],
    [bottomLeft, topLeft],
  ][edge];
  const fraction = (level - edgeValues[0]) / (edgeValues[1] - edgeValues[0]);
  if (edge === 0) return [column + fraction, row];
  if (edge === 1) return [column + 1, row + fraction];
  if (edge === 2) return [column + 1 - fraction, row + 1];
  return [column, row + 1 - fraction];
};

const cellSegments = (column, row, values, level) => {
  const pairs = [
    [0, 1],
    [1, 2],
    [2, 3],
    [3, 0],
  ];
  const edges = pairs.flatMap(([start, end], edge) =>
    values[start] < level !== values[end] < level ? [edge] : [],
  );
  if (edges.length === 2) {
    return [
      [
        edgePoint(edges[0], column, row, values, level),
        edgePoint(edges[1], column, row, values, level),
      ],
    ];
  }
  if (edges.length !== 4) return [];
  const centerIsHigh =
    values.reduce((sum, value) => sum + value, 0) / 4 >= level;
  const pairings = centerIsHigh
    ? [
        [0, 1],
        [2, 3],
      ]
    : [
        [0, 3],
        [1, 2],
      ];
  return pairings.map(([first, second]) => [
    edgePoint(first, column, row, values, level),
    edgePoint(second, column, row, values, level),
  ]);
};

const joinSegments = (segments) => {
  const adjacency = new Map();
  segments.forEach((segment, index) =>
    segment.forEach((point) => {
      const key = pointKey(point);
      if (!adjacency.has(key)) adjacency.set(key, []);
      adjacency.get(key).push(index);
    }),
  );
  const used = new Set();
  const paths = [];
  const walk = (firstIndex, firstPoint) => {
    const path = [firstPoint];
    let segmentIndex = firstIndex;
    let currentKey = pointKey(firstPoint);
    while (segmentIndex !== undefined && !used.has(segmentIndex)) {
      used.add(segmentIndex);
      const segment = segments[segmentIndex];
      const next =
        pointKey(segment[0]) === currentKey ? segment[1] : segment[0];
      path.push(next);
      currentKey = pointKey(next);
      segmentIndex = adjacency
        .get(currentKey)
        ?.find((candidate) => !used.has(candidate));
    }
    if (path.length >= 3) paths.push(path);
  };
  segments.forEach((segment, index) => {
    if (used.has(index)) return;
    const start = segment.find(
      (point) => adjacency.get(pointKey(point))?.length === 1,
    );
    if (start) walk(index, start);
  });
  segments.forEach((segment, index) => {
    if (!used.has(index)) walk(index, segment[0]);
  });
  return paths;
};

const adjacentCellIndexes = (coordinate) => {
  const rounded = Math.round(coordinate);
  return Math.abs(coordinate - rounded) <= GRID_EPSILON
    ? [rounded - 1, rounded]
    : [Math.floor(coordinate)];
};

const endpointTouchesNoData = ([x, y], values, width, height) => {
  const columns = adjacentCellIndexes(x);
  const rows = adjacentCellIndexes(y);
  return rows.some((row) =>
    columns.some((column) => {
      if (column < 0 || row < 0 || column >= width - 1 || row >= height - 1) {
        return false;
      }
      const index = row * width + column;
      return [
        values[index],
        values[index + 1],
        values[index + width + 1],
        values[index + width],
      ].some((value) => !Number.isFinite(value));
    }),
  );
};

const pathLengthInNativeUnits = (path, xResolution, yResolution) => {
  let length = 0;
  for (let index = 1; index < path.length; index += 1) {
    length += Math.hypot(
      (path[index][0] - path[index - 1][0]) * xResolution,
      (path[index][1] - path[index - 1][1]) * yResolution,
    );
  }
  return length;
};

const threePointInteriorAngle = (path, xResolution, yResolution) => {
  const [first, middle, last] = path;
  const firstVector = [
    (first[0] - middle[0]) * xResolution,
    (first[1] - middle[1]) * yResolution,
  ];
  const lastVector = [
    (last[0] - middle[0]) * xResolution,
    (last[1] - middle[1]) * yResolution,
  ];
  const denominator = Math.hypot(...firstVector) * Math.hypot(...lastVector);
  if (denominator === 0) return Math.PI;
  const cosine = Math.max(
    -1,
    Math.min(
      1,
      (firstVector[0] * lastVector[0] + firstVector[1] * lastVector[1]) /
        denominator,
    ),
  );
  return Math.acos(cosine);
};

const isTinyNoDataBoundaryFragment = (
  path,
  values,
  width,
  height,
  xResolution,
  yResolution,
) => {
  if (path.length > 3 || pointKey(path[0]) === pointKey(path.at(-1))) {
    return false;
  }
  if (
    !endpointTouchesNoData(path[0], values, width, height) &&
    !endpointTouchesNoData(path.at(-1), values, width, height)
  ) {
    return false;
  }
  if (
    pathLengthInNativeUnits(path, xResolution, yResolution) >=
    MAX_NODATA_FRAGMENT_LENGTH
  ) {
    return false;
  }
  return (
    path.length !== 3 ||
    threePointInteriorAngle(path, xResolution, yResolution) <
      MAX_NODATA_FRAGMENT_ANGLE
  );
};

const decodeRaster = async (item, overviewIndex) => {
  const tiff = await fromUrl(item.products.cov.browserHref, {
    blockSize: 1024 * 1024,
    cacheSize: 32,
  });
  const imageCount = await tiff.getImageCount();
  if (overviewIndex < 0 || overviewIndex >= imageCount) {
    throw new Error(
      `Fixed overview index ${overviewIndex} is unavailable (${imageCount} images)`,
    );
  }
  const baseImage = await tiff.getImage(0);
  const image = await tiff.getImage(overviewIndex);
  const width = image.getWidth();
  const height = image.getHeight();
  const raster = await image.readRasters({
    samples: [0, 1, 2],
    interleave: true,
  });
  const band = item.products.cov;
  const values = new Float32Array(width * height);
  for (let index = 0; index < values.length; index += 1) {
    const mean = raster[index * 3];
    const cov = raster[index * 3 + 1];
    const aoa = raster[index * 3 + 2];
    const valid =
      mean !== item.products.mean.nodata &&
      cov !== band.nodata &&
      aoa !== item.products.aoa.nodata;
    values[index] = valid
      ? cov * (band.scale || 1) + (band.offset ?? 0)
      : Number.NaN;
  }
  const [minX, minY, maxX, maxY] = baseImage.getBoundingBox();
  const xResolution = (maxX - minX) / width;
  const yResolution = (maxY - minY) / height;
  return {
    values,
    width,
    height,
    geotransform: [minX, xResolution, 0, maxY, 0, -yResolution],
    bbox: [minX, minY, maxX, maxY],
    crs: item.properties?.["proj:code"] ?? null,
    overviewIndex,
    bands: {
      mean: {
        band: item.products.mean.band,
        nodata: item.products.mean.nodata,
        scale: item.products.mean.scale ?? 1,
        offset: item.products.mean.offset ?? 0,
      },
      cov: {
        band: item.products.cov.band,
        nodata: item.products.cov.nodata,
        scale: item.products.cov.scale ?? 1,
        offset: item.products.cov.offset ?? 0,
      },
      aoa: {
        band: item.products.aoa.band,
        nodata: item.products.aoa.nodata,
        scale: item.products.aoa.scale ?? 1,
        offset: item.products.aoa.offset ?? 0,
      },
    },
  };
};

const generateContours = (raster, levels) => {
  const { values, width, height, bbox } = raster;
  const [minX, minY, maxX, maxY] = bbox;
  const xResolution = (maxX - minX) / width;
  const yResolution = (maxY - minY) / height;
  const descriptors = [];
  const removedByLevel = Object.fromEntries(
    levels.map((level) => [String(level), 0]),
  );
  for (let levelIndex = 0; levelIndex < levels.length; levelIndex += 1) {
    const level = levels[levelIndex];
    const segments = [];
    for (let row = 0; row < height - 1; row += 1) {
      for (let column = 0; column < width - 1; column += 1) {
        const index = row * width + column;
        const cell = [
          values[index],
          values[index + 1],
          values[index + width + 1],
          values[index + width],
        ];
        if (cell.every(Number.isFinite))
          segments.push(...cellSegments(column, row, cell, level));
      }
    }
    joinSegments(segments).forEach((path) => {
      if (
        isTinyNoDataBoundaryFragment(
          path,
          values,
          width,
          height,
          xResolution,
          yResolution,
        )
      ) {
        removedByLevel[String(level)] += 1;
        return;
      }
      descriptors.push({
        level,
        coordinates: path.map(([x, y]) => [
          minX + x * xResolution,
          maxY - y * yResolution,
        ]),
      });
    });
    globalThis.postMessage({
      type: "progress",
      done: levelIndex + 1,
      total: levels.length,
    });
  }
  return {
    descriptors,
    filterStats: {
      removedTotal: Object.values(removedByLevel).reduce(
        (sum, count) => sum + count,
        0,
      ),
      removedByLevel,
      maximumLength: MAX_NODATA_FRAGMENT_LENGTH,
      maximumInteriorAngleDegrees: (MAX_NODATA_FRAGMENT_ANGLE * 180) / Math.PI,
    },
  };
};

globalThis.addEventListener("message", async ({ data }) => {
  try {
    if (data.jobType === "decode-raster") {
      const raster = await decodeRaster(data.item, data.overviewIndex);
      globalThis.postMessage({ type: "complete", result: raster }, [
        raster.values.buffer,
      ]);
      return;
    }
    if (data.jobType === "generate-contours") {
      const descriptors = generateContours(data.raster, data.levels);
      globalThis.postMessage({ type: "complete", result: descriptors });
      return;
    }
    throw new Error(`Unknown contour worker job: ${data.jobType}`);
  } catch (error) {
    globalThis.postMessage({
      type: "error",
      message: error.stack ?? error.message,
    });
  }
});
