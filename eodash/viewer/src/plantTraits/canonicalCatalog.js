const LOCAL_REPOSITORY_BASE = "http://localhost:8000/";

const repositoryBaseUrl =
  import.meta.env.VITE_EODASH_REPOSITORY_BASE_URL ||
  (import.meta.env.DEV
    ? LOCAL_REPOSITORY_BASE
    : new URL(import.meta.env.BASE_URL, window.location.origin).href);

export const stacEndpoint =
  import.meta.env.VITE_EODASH_STAC_ENDPOINT ||
  new URL("stac_catalogs/stac_catalog_v1/catalog.json", repositoryBaseUrl).href;

export const repositoryUrl = (path) => new URL(path, repositoryBaseUrl).href;

const jsonCache = new Map();

const fetchJson = (url) => {
  if (jsonCache.has(url)) return jsonCache.get(url);
  const request = fetch(url)
    .then((response) => {
      if (!response.ok)
        throw new Error(`${response.status} ${response.statusText}: ${url}`);
      return response.json();
    })
    .catch((error) => {
      jsonCache.delete(url);
      throw error;
    });
  jsonCache.set(url, request);
  return request;
};

const toBrowserReadableAssetUrl = (href) => {
  const url = new URL(href);
  if (url.hostname !== "zenodo.org") return href;
  const match = /^\/records\/([^/]+)\/files\/(.+)$/.exec(url.pathname);
  if (!match) return href;
  return new URL(
    `/api/records/${encodeURIComponent(match[1])}/files/${match[2]}/content`,
    url.origin,
  ).href;
};

const classifyBands = (item, visualization) => {
  const products = {};
  for (const [product, expected] of Object.entries(
    visualization.assetProducts,
  )) {
    const asset = item.assets?.[expected.assetKey];
    if (!asset)
      throw new Error(`${item.id}: missing asset ${expected.assetKey}`);
    const bands = asset["raster:bands"] ?? [];
    const index = bands.findIndex((band) => band.name === expected.bandName);
    if (index < 0 || index + 1 !== expected.band) {
      throw new Error(
        `${item.id}: expected ${product} as ${expected.bandName} in band ${expected.band}`,
      );
    }
    products[product] = {
      ...expected,
      ...bands[index],
      canonicalHref: asset.href,
      browserHref: visualization.browserAccess?.zenodoApiContent
        ? toBrowserReadableAssetUrl(asset.href)
        : asset.href,
      type: asset.type,
      roles: asset.roles ?? [],
    };
  }
  return products;
};

export const loadVisualizationConfig = async () => {
  const configUrl = repositoryUrl(
    "eodash/config/plant-trait-visualization.json",
  );
  const config = await fetchJson(configUrl);
  const styles = Object.fromEntries(
    await Promise.all(
      Object.entries(config.styles).map(async ([name, href]) => [
        name,
        await fetchJson(new URL(href, configUrl).href),
      ]),
    ),
  );
  return { ...config, resolvedStyles: styles };
};

const loadCatalogCollection = async (visualization) => {
  const catalog = await fetchJson(stacEndpoint);
  const childLinks =
    catalog.links?.filter((link) => link.rel === "child") ?? [];
  let collectionUrl;
  let collection;
  for (const link of childLinks) {
    const candidateUrl = new URL(link.href, stacEndpoint).href;
    const candidate = await fetchJson(candidateUrl);
    if (candidate.id === visualization.collectionId) {
      collectionUrl = candidateUrl;
      collection = candidate;
      break;
    }
  }
  if (!collection) {
    throw new Error(
      `Collection ${visualization.collectionId} not found below ${stacEndpoint}`,
    );
  }
  return { catalog, collection, collectionUrl };
};

/**
 * Build the selector from every canonical STAC item whose primary raster was
 * confirmed by the build-time availability preprocessing step.
 */
export const loadCanonicalPlantTraitIndex = async (visualization) => {
  const [canonical, inventory, availability] = await Promise.all([
    loadCatalogCollection(visualization),
    fetchJson(repositoryUrl("eodash/config/asset-inventory.json")),
    fetchJson(repositoryUrl("eodash/config/trait-availability.json")),
  ]);
  const inventoryCollection = inventory.collections?.find(
    (candidate) => candidate.id === visualization.collectionId,
  );
  if (!inventoryCollection) {
    throw new Error(
      `Collection ${visualization.collectionId} missing from asset inventory`,
    );
  }
  const availabilityById = new Map(
    availability.items?.map((entry) => [entry.id, entry]) ?? [],
  );
  const itemLinks = new Map(
    (canonical.collection.links ?? [])
      .filter((link) => link.rel === "item")
      .map((link) => {
        const itemUrl = new URL(link.href, canonical.collectionUrl).href;
        return [
          decodeURIComponent(
            new URL(itemUrl).pathname
              .split("/")
              .at(-1)
              .replace(/\.json$/, ""),
          ),
          itemUrl,
        ];
      }),
  );
  const items = inventoryCollection.items
    .filter((entry) => {
      const checked = availabilityById.get(entry.id);
      return (
        checked?.available === true &&
        checked.href === entry.assets?.mean?.href
      );
    })
    .map((entry) => {
      const canonicalItemUrl = itemLinks.get(entry.id);
      if (!canonicalItemUrl)
        throw new Error(`${entry.id}: canonical item link is missing`);
      return {
        id: entry.id,
        title: entry.title ?? entry.id,
        canonicalItemUrl,
      };
    });
  items.sort((left, right) => left.title.localeCompare(right.title));
  return { ...canonical, items };
};

export const loadCanonicalPlantTrait = async (entry, visualization) => {
  const item = await fetchJson(entry.canonicalItemUrl);
  return {
    ...item,
    canonicalItemUrl: entry.canonicalItemUrl,
    title:
      item.properties?.trait_short_name ??
      item.properties?.title ??
      entry.title ??
      item.id,
    products: classifyBands(item, visualization),
  };
};
