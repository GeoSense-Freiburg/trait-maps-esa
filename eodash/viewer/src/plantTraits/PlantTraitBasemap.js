import GeoJSON from "ol/format/GeoJSON.js";
import VectorLayer from "ol/layer/Vector.js";
import VectorSource from "ol/source/Vector.js";
import Style from "ol/style/Style.js";
import Fill from "ol/style/Fill.js";
import Stroke from "ol/style/Stroke.js";
import { repositoryUrl } from "./canonicalCatalog";

const COUNTRIES_URL = repositoryUrl(
  "eodash/reference/ne_110m_admin_0_countries.geojson",
);
let basemapSourcePromise;

const basemapStyle = new Style({
  fill: new Fill({ color: "rgba(238,240,237,0.96)" }),
  stroke: new Stroke({ color: "rgba(70,78,82,0.38)", width: 0.7 }),
});

const loadBasemapSource = (mapProjection) => {
  if (!basemapSourcePromise) {
    basemapSourcePromise = fetch(COUNTRIES_URL).then((response) => {
      if (!response.ok)
        throw new Error(
          `${response.status} ${response.statusText}: ${COUNTRIES_URL}`,
        );
      return response.json();
    });
  }
  return basemapSourcePromise.then((geojson) => {
    const features = new GeoJSON().readFeatures(geojson, {
      dataProjection: "EPSG:4326",
      featureProjection: mapProjection,
    });
    return new VectorSource({ features, wrapX: false });
  });
};

export const installNaturalEarthBasemap = async (map, mapProjection) => {
  const existing = map
    .getLayers()
    .getArray()
    .find((layer) => layer.get("id") === "natural-earth-basemap");
  if (existing) {
    existing.setVisible(true);
    return existing;
  }
  const source = await loadBasemapSource(mapProjection);
  const layer = new VectorLayer({
    source,
    style: basemapStyle,
    declutter: false,
    updateWhileAnimating: false,
    updateWhileInteracting: false,
    zIndex: -100,
  });
  layer.set("id", "natural-earth-basemap");
  layer.set("title", "Natural Earth land and borders");
  layer.set("plantTraitBasemap", true);
  layer.set("layerControlExclusive", true);
  layer.getAttributions = () => ["Natural Earth, public domain"];
  map.getLayers().insertAt(0, layer);
  return layer;
};
