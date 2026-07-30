const rasterCache = new Map();
const derivedResultCache = new Map();
const resourceCache = new Map();
const countersByKey = new Map();

const emptyCounters = () => ({
  rasterFetchCount: 0,
  rasterDecodeCount: 0,
  workerJobCount: 0,
  contourGenerationCount: 0,
  aoaGenerationCount: 0,
  cacheHitCount: 0,
  cacheMissCount: 0,
});

const countersFor = (key) => {
  if (!countersByKey.has(key)) countersByKey.set(key, emptyCounters());
  return countersByKey.get(key);
};

export const incrementDerivedCounter = (key, counter) => {
  if (!import.meta.env.DEV) return;
  const counters = countersFor(key);
  counters[counter] = (counters[counter] ?? 0) + 1;
};

const cachedPromise = (cache, key, loader) => {
  const existing = cache.get(key);
  if (existing) {
    incrementDerivedCounter(key, "cacheHitCount");
    return existing.state === "ready"
      ? Promise.resolve(existing.value)
      : existing.promise;
  }

  incrementDerivedCounter(key, "cacheMissCount");
  const promise = Promise.resolve().then(loader);
  const pending = { state: "pending", promise };
  cache.set(key, pending);
  promise.then(
    (value) => {
      if (cache.get(key) === pending) cache.set(key, { state: "ready", value });
    },
    () => {
      if (cache.get(key) === pending) cache.delete(key);
    },
  );
  return promise;
};

export const getOrCreateRasterData = (key, loader) =>
  cachedPromise(rasterCache, key, loader);

export const getOrCreateDerivedResult = (key, loader) =>
  cachedPromise(derivedResultCache, key, loader);

export const getOrCreateDerivedResource = (key, factory) => {
  if (resourceCache.has(key)) {
    incrementDerivedCounter(key, "cacheHitCount");
    return resourceCache.get(key);
  }
  incrementDerivedCounter(key, "cacheMissCount");
  const resource = factory();
  resourceCache.set(key, resource);
  return resource;
};

export const assetVersionFor = (item, product) => {
  const asset = item.assets?.[product.assetKey] ?? {};
  return (
    asset["file:checksum"] ??
    asset["checksum:multihash"] ??
    asset.version ??
    item.properties?.version ??
    item.properties?.updated ??
    item.properties?.datetime ??
    "unversioned"
  );
};

export const stableDerivedKey = (kind, fields) =>
  JSON.stringify({ kind, ...fields });

export const getDerivedCacheSnapshot = () => {
  const totals = emptyCounters();
  const byKey = Object.fromEntries(
    [...countersByKey].map(([key, value]) => {
      Object.keys(totals).forEach((counter) => {
        totals[counter] += value[counter] ?? 0;
      });
      return [key, { ...value }];
    }),
  );
  return {
    totals,
    byKey,
    entries: {
      raster: rasterCache.size,
      derivedResult: derivedResultCache.size,
      resource: resourceCache.size,
    },
  };
};

if (import.meta.env.DEV) {
  globalThis.__EODASH_DERIVED_CACHE__ = {
    snapshot: getDerivedCacheSnapshot,
  };
}
