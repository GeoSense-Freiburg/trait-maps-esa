import Map from "ol/Map.js";
import View from "ol/View.js";
import TileLayer from "ol/layer/Tile.js";
import OSM from "ol/source/OSM.js";
import { transformExtent } from "ol/proj.js";
import {
  loadCanonicalPlantTrait,
  loadCanonicalPlantTraitIndex,
  loadVisualizationConfig,
  stacEndpoint,
} from "../plantTraits/canonicalCatalog";
import { createPlantTraitLayerGroup } from "../plantTraits/PlantTraitMapLayers";
import "ol/ol.css";

document.title = "Remote canonical COG diagnostic";
document.body.innerHTML = `
  <style>html,body,#remote-cog-map{margin:0;width:100%;height:100%}#status{position:absolute;z-index:2;top:12px;left:12px;max-width:520px;padding:10px;background:#ffffffe8;border-radius:4px;font:13px/1.4 system-ui;white-space:pre-wrap}</style>
  <div id="remote-cog-map"></div><div id="status">Loading canonical STAC and first mean asset…</div>
`;

const status = document.querySelector("#status");
const nativeFetch = window.fetch.bind(window);
window.remoteCogRequestSummary = { total: 0, statuses: {}, recent: [] };
const recordRemoteRequest = (entry) => {
  const summary = window.remoteCogRequestSummary;
  summary.total += 1;
  const statusKey = String(entry.status ?? "error");
  summary.statuses[statusKey] = (summary.statuses[statusKey] ?? 0) + 1;
  summary.recent.push(entry);
  summary.recent.splice(0, Math.max(0, summary.recent.length - 50));
};
window.fetch = async (input, init) => {
  const url = typeof input === "string" ? input : input.url;
  try {
    const response = await nativeFetch(input, init);
    if (url.includes("zenodo.org")) {
      recordRemoteRequest({
        url,
        method: init?.method ?? "GET",
        range: new Headers(init?.headers).get("range"),
        status: response.status,
        contentRange: response.headers.get("content-range"),
        cors: response.headers.get("access-control-allow-origin"),
      });
    }
    return response;
  } catch (error) {
    if (url.includes("zenodo.org")) {
      recordRemoteRequest({ url, error: error.message });
    }
    throw error;
  }
};

try {
  const visualization = await loadVisualizationConfig();
  const canonical = await loadCanonicalPlantTraitIndex(visualization);
  const entry =
    canonical.items.find(
      (candidate) => candidate.id === visualization.initialItemId,
    ) ?? canonical.items[0];
  const item = await loadCanonicalPlantTrait(entry, visualization);
  const layers = createPlantTraitLayerGroup(item, visualization);
  layers.cov.setVisible(false);
  layers.aoa.setVisible(false);
  const map = new Map({
    target: "remote-cog-map",
    layers: [new TileLayer({ source: new OSM() }), layers.mean],
    view: new View({ center: [0, 0], zoom: 2 }),
  });
  for (const eventName of ["tileloaderror", "error"]) {
    layers.mean
      .getSource()
      .on(eventName, (event) =>
        console.error(`Remote GeoTIFF ${eventName}`, event),
      );
  }
  layers.mean
    .getSource()
    .on("change", () =>
      console.log(
        "Remote GeoTIFF source state",
        layers.mean.getSource().getState(),
      ),
    );
  window.remoteCogDiagnostic = { map, item, layers, sourceView: null };
  const sourceView = await layers.mean.getSource().getView();
  window.remoteCogDiagnostic.sourceView = sourceView;
  console.log("Remote GeoTIFF source view", sourceView);
  console.log(
    "Canonical item and asset",
    item.canonicalItemUrl,
    item.products.mean,
  );
  map.getView().fit(transformExtent(item.bbox, "EPSG:4326", "EPSG:3857"), {
    size: map.getSize(),
    padding: [30, 30, 30, 30],
    maxZoom: 5,
  });
  status.textContent = `Canonical STAC: ${stacEndpoint}\nItem: ${
    item.id
  }\nCanonical asset: ${item.products.mean.canonicalHref}\nBrowser endpoint: ${
    item.products.mean.browserHref
  }\nSource state: ${layers.mean.getSource().getState()}`;
} catch (error) {
  console.error("Remote COG diagnostic failed", error);
  status.textContent = `FAILED\n${error.stack ?? error.message}`;
  status.style.color = "#b71c1c";
}
