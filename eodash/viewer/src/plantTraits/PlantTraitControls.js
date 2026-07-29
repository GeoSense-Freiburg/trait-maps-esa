import {
  loadCanonicalPlantTrait,
  loadCanonicalPlantTraitIndex,
  loadVisualizationConfig,
  stacEndpoint,
} from "./canonicalCatalog";
import { installNaturalEarthBasemap } from "./PlantTraitBasemap";
import { getCenter } from "ol/extent.js";
import { transform } from "ol/proj.js";
import {
  createPlantTraitLayerGroup,
  fitItem,
  formatMeanStops,
  readPlantTraitValuesAtPixel,
  sampleMeanStyle,
} from "./PlantTraitMapLayers";
import { COV_CONTOUR_LEVELS, covColorForValue } from "./CovPalette";
import { datasetInformationMarkup } from "./DatasetInformation";
const tagName = "plant-trait-controls";
const eyeOpen = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2.2 12s3.6-6 9.8-6 9.8 6 9.8 6-3.6 6-9.8 6-9.8-6-9.8-6Z"/><circle cx="12" cy="12" r="3.1"/></svg>`;
const eyeClosed = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 3 21 21M10.6 6.1C11 6 11.5 6 12 6c6.2 0 9.8 6 9.8 6a16 16 0 0 1-3 3.6M14.6 17.7c-.8.2-1.7.3-2.6.3-6.2 0-9.8-6-9.8-6a17 17 0 0 1 4-4.4M9.8 9.8a3.1 3.1 0 0 0 4.4 4.4"/></svg>`;
const DATA_PROJECTION = "EPSG:6933";
const DATA_PROJ4 =
  "+proj=cea +lat_ts=30 +lon_0=0 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs";
const DATA_EXTENT = [
  -17367530.445161372, -7342230.205017054, 17367530.445161372,
  7342230.205017056,
];
const COV_HELP =
  "Coefficient of variation (CoV) expresses the variation among model predictions relative to the predicted trait value. Lower values indicate more consistent predictions, while higher values indicate greater uncertainty. CoV should be interpreted together with the predicted trait value and the Area of Applicability.";
const COV_PERCENT_HELP =
  "For example, a CoV of 4% means that variation among the model predictions is approximately 4% of the predicted trait value.";
const AOA_HELP =
  "Area of Applicability (AoA) indicates whether the environmental conditions at this location are sufficiently similar to those represented in the model training data. Predictions inside the AoA are better supported by the training data. Predictions outside the AoA should be interpreted with greater caution.";
const tickFormatter = new Intl.NumberFormat("en", {
  maximumSignificantDigits: 3,
});

const waitForMap = async () => {
  for (let attempt = 0; attempt < 480; attempt += 1) {
    const map = window.eodashStore?.states?.mapEl?.value?.map;
    if (map) return map;
    await new Promise((resolve) => window.setTimeout(resolve, 250));
  }
  throw new Error("EO Dashboard map was not created within two minutes");
};

const setEye = (button, visible) => {
  button.dataset.visible = String(visible);
  button.setAttribute("aria-pressed", String(visible));
  button.setAttribute(
    "aria-label",
    `${visible ? "Hide" : "Show"} ${button.dataset.name}`,
  );
  button.title = `${visible ? "Hide" : "Show"} ${button.dataset.name}`;
  button.innerHTML = visible ? eyeOpen : eyeClosed;
};

if (!customElements.get(tagName)) {
  customElements.define(
    tagName,
    class PlantTraitControls extends HTMLElement {
      async connectedCallback() {
        this.innerHTML = `<p style="padding:16px;font:14px system-ui">Loading trait index…</p>`;
        try {
          this.visualization = await loadVisualizationConfig();
          this.canonical = await loadCanonicalPlantTraitIndex(
            this.visualization,
          );
          this.map = await waitForMap();
          await this.configureScientificProjection();
          await this.installBasemaps();
          this.renderControls();
          const searchParams = new URL(window.location.href).searchParams;
          const requested = searchParams.get("trait");
          const hasRequestedView = ["x", "y", "z"].every((name) =>
            searchParams.has(name),
          );
          const initial =
            this.canonical.items.find((item) => item.id === requested) ??
            this.canonical.items.find(
              (item) => item.id === this.visualization.initialItemId,
            ) ??
            this.canonical.items[0];
          await this.selectTrait(initial.id, !hasRequestedView);
        } catch (error) {
          console.error(
            "Failed to initialize canonical plant-trait view",
            error,
          );
          this.innerHTML = `<p style="padding:16px;color:#b71c1c;font:14px system-ui">${error.message}</p>`;
        }
      }

      disconnectedCallback() {
        if (this.pointerHandler && this.map)
          this.map.un("pointermove", this.pointerHandler);
        if (this.hoverLeaveHandler && this.map) {
          this.map
            .getViewport()
            .removeEventListener("pointerleave", this.hoverLeaveHandler);
        }
        if (this.layers?.group && this.map)
          this.map.removeLayer(this.layers.group);
        if (this.hoverFrame) window.cancelAnimationFrame(this.hoverFrame);
        document.removeEventListener("pointerdown", this.helpOutsideHandler);
        document.removeEventListener("keydown", this.helpKeyHandler);
      }

      renderControls() {
        const covStyle = this.visualization.resolvedStyles.cov;
        const aoaStyle = this.visualization.resolvedStyles.aoa;
        this.innerHTML = `
          <style>
            plant-trait-controls { display:block;box-sizing:border-box;height:100%;padding:14px 16px;color:#263238;font:14px/1.35 system-ui,sans-serif;overflow:auto }
            .v-app-bar-title.header { font-weight:650;letter-spacing:.01em }
            plant-trait-controls .visually-hidden { position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0 }
            plant-trait-controls .dataset-card { margin:0 0 14px;padding:11px 12px;border:1px solid #d6e0dc;border-radius:8px;background:rgba(248,250,249,.96);box-shadow:0 1px 3px rgba(20,40,45,.08) }
            plant-trait-controls .dataset-card-head { display:flex;align-items:center;justify-content:space-between;gap:10px }
            plant-trait-controls .dataset-card h2 { margin:0;color:#18343f;font-size:15px;font-weight:700;letter-spacing:.01em }
            plant-trait-controls .dataset-card-body { margin-top:6px }
            plant-trait-controls .dataset-card.is-collapsed .dataset-card-body { display:none }
            plant-trait-controls .dataset-summary { margin:0 0 9px;color:#3e5058;font-size:11.5px;line-height:1.4 }
            plant-trait-controls .dataset-metadata { display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px 12px;margin:0 }
            plant-trait-controls .dataset-metadata div { min-width:0 }
            plant-trait-controls .dataset-metadata .metadata-wide { grid-column:1/-1 }
            plant-trait-controls .dataset-metadata dt { color:#68777e;font-size:9.5px;font-weight:700;letter-spacing:.045em;text-transform:uppercase }
            plant-trait-controls .dataset-metadata dd { margin:1px 0 0;color:#263238;font-size:11px;line-height:1.35;overflow-wrap:anywhere }
            plant-trait-controls .dataset-metadata cite { font-style:normal }
            plant-trait-controls .dataset-card a { color:#005f87;font-weight:650;text-decoration-thickness:1px;text-underline-offset:2px }
            plant-trait-controls .dataset-card a:hover { color:#003f5c }
            plant-trait-controls .dataset-card a:focus-visible { outline:2px solid #0878a8;outline-offset:2px;border-radius:2px }
            plant-trait-controls .dataset-links { display:flex;flex-wrap:wrap;gap:6px 12px;margin-top:9px;padding-top:8px;border-top:1px solid #dce4e1 }
            plant-trait-controls .dataset-link { font-size:11px;white-space:nowrap }
            @media (max-width:420px) { plant-trait-controls .dataset-metadata { grid-template-columns:1fr } plant-trait-controls .dataset-metadata .metadata-wide { grid-column:auto } }
            plant-trait-controls label { display:block;margin:0 0 5px;color:#52616b;font-size:12px;font-weight:700;letter-spacing:.04em;text-transform:uppercase }
            plant-trait-controls select { box-sizing:border-box;width:100%;margin-bottom:10px;padding:7px;border:1px solid #9eabb3;border-radius:4px;background:#fff }
            plant-trait-controls .panel-head { display:flex;align-items:center;justify-content:space-between;margin:0 0 12px;color:#263238;font-size:13px;font-weight:700 }
            plant-trait-controls .collapse { width:28px;height:28px;border:1px solid #aab7bd;border-radius:4px;background:#fff;color:#004170;font-size:20px;line-height:20px;cursor:pointer }
            plant-trait-controls.is-collapsed { height:auto;overflow:hidden }
            plant-trait-controls.is-collapsed .control-body { display:none }
            plant-trait-controls .layer { display:grid;grid-template-columns:32px 1fr;gap:5px 8px;align-items:center;margin:10px 0;padding-top:8px;border-top:1px solid #d7e0dc }
            plant-trait-controls .layer-name { color:#263238;font-size:13px;font-weight:700 }
            plant-trait-controls .eye { display:grid;place-items:center;width:30px;height:30px;padding:4px;border:0;border-radius:50%;color:#004170;background:#e7f0ed;cursor:pointer }
            plant-trait-controls .eye[data-visible=false] { color:#7b8991;background:#f1f3f3 }
            plant-trait-controls .eye svg { width:22px;height:22px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round }
            plant-trait-controls .opacity { grid-column:2;display:grid;grid-template-columns:auto 1fr 40px;gap:7px;align-items:center }
            plant-trait-controls .opacity label { margin:0;text-transform:none;letter-spacing:0;font-size:11px }
            plant-trait-controls input[type=range] { width:100%;min-width:0 }
            plant-trait-controls output { text-align:right;font-size:11px;font-variant-numeric:tabular-nums }
            plant-trait-controls .mode { grid-column:2 }
            plant-trait-controls .mode select { margin:0 }
            plant-trait-controls .value { margin-top:10px;padding:7px;background:#eef4f1;border-radius:4px;font-variant-numeric:tabular-nums }
            plant-trait-controls .hover-row + .hover-row { margin-top:5px }
            plant-trait-controls .hover-label { display:block;color:#52616b;font-size:11px;font-weight:700 }
            plant-trait-controls .legend-panel { margin-top:10px;padding-top:2px;border-top:1px solid #d7e0dc;font-size:11px }
            plant-trait-controls .legend-section { position:relative;margin-top:9px }
            plant-trait-controls .legend-title { display:flex;align-items:center;gap:5px;margin-bottom:5px;color:#263238;font-size:12px;font-weight:700 }
            plant-trait-controls .help-button { display:inline-grid;place-items:center;width:18px;height:18px;padding:0;border:1px solid #80919a;border-radius:50%;background:#fff;color:#40545e;font:700 12px/1 system-ui;cursor:pointer }
            plant-trait-controls .help-button:focus-visible { outline:2px solid #0878a8;outline-offset:2px }
            plant-trait-controls .help-popover { position:absolute;z-index:20;top:23px;left:0;box-sizing:border-box;width:min(260px,100%);padding:9px;border:1px solid #87979f;border-radius:5px;background:#fff;color:#263238;box-shadow:0 3px 10px rgba(20,28,32,.22);font-size:11px;line-height:1.4 }
            plant-trait-controls .help-popover p { margin:0 }
            plant-trait-controls .help-popover p + p { margin-top:6px }
            plant-trait-controls .colorbar { width:100%;height:12px;border:1px solid rgba(38,50,56,.35);border-radius:2px }
            plant-trait-controls .legend-ticks { display:flex;justify-content:space-between;gap:3px;margin-top:2px;color:#52616b;font-size:10px;white-space:nowrap }
            plant-trait-controls .legend-key { display:flex;flex-wrap:wrap;gap:5px 9px }
            plant-trait-controls .legend-key-item { display:inline-flex;align-items:center;gap:4px;white-space:nowrap }
            plant-trait-controls .line-swatch { width:20px;border-top:3px solid currentColor }
            plant-trait-controls .state-swatch { display:inline-grid;place-items:center;width:20px;height:12px;border:1px solid #8c9aa1;border-radius:2px;background:transparent;font-size:12px;font-weight:800;line-height:1 }
            plant-trait-controls .aoa-outside { color:${aoaStyle.crossColor} }
            plant-trait-controls .aoa-inside { color:#40545e }
            plant-trait-controls .status { min-height:16px;margin-top:6px;color:#52616b;font-size:11px }
            plant-trait-controls .source { margin-top:7px;color:#65747d;font-size:10px;overflow-wrap:anywhere }
          </style>
          ${datasetInformationMarkup(this.canonical.collection)}
          <div class="panel-head"><span>Map controls</span><button id="collapse-controls" class="collapse" type="button" aria-expanded="true" aria-label="Minimize map controls" title="Minimize">−</button></div>
          <div class="control-body">
          <label for="trait-select">Plant trait</label>
          <select id="trait-select">${this.canonical.items
            .map((item) => `<option value="${item.id}">${item.title}</option>`)
            .join("")}</select>
          <label for="basemap-select">Base map</label>
          <select id="basemap-select"><option value="natural-earth">Natural Earth reference</option></select>
          ${this.layerRow("mean", "Trait data", true, 1)}
          ${this.layerRow(
            "cov",
            "CoV uncertainty",
            false,
            covStyle.opacity,
            true,
          )}
          ${this.layerRow("aoa", "AoA outside warning", true, 1)}
          <div class="value" id="hover-value">Move over the map to inspect the mean value.</div>
          <div class="legend-panel" aria-label="Map legends">
            <section class="legend-section" id="trait-legend-section">
              <div class="legend-title" id="trait-legend-title">Trait</div>
              <div class="colorbar" id="trait-colorbar" role="img"></div>
              <div class="legend-ticks" id="trait-legend-ticks"></div>
            </section>
            <section class="legend-section" id="cov-legend-section" hidden>
              <div class="legend-title">CoV <button class="help-button" type="button" data-help="cov" aria-label="About coefficient of variation" aria-expanded="false" aria-controls="cov-help">?</button></div>
              <div class="help-popover" id="cov-help" role="dialog" aria-label="Coefficient of variation explanation" tabindex="-1" hidden><p>${COV_HELP}</p><p>${COV_PERCENT_HELP}</p></div>
              <div id="cov-legend-content"></div>
            </section>
            <section class="legend-section" id="aoa-legend-section">
              <div class="legend-title">AoA <button class="help-button" type="button" data-help="aoa" aria-label="About Area of Applicability" aria-expanded="false" aria-controls="aoa-help">?</button></div>
              <div class="help-popover" id="aoa-help" role="dialog" aria-label="Area of Applicability explanation" tabindex="-1" hidden><p>${AOA_HELP}</p></div>
              <div class="legend-key"><span class="legend-key-item"><span class="state-swatch aoa-inside" aria-hidden="true">✓</span>Inside AoA</span><span class="legend-key-item"><span class="state-swatch aoa-outside" aria-hidden="true">×</span>Outside AoA</span></div>
            </section>
          </div>
          <div class="status" id="layer-status"></div>
          <div class="source">Canonical catalog: ${stacEndpoint}</div>
          </div>
        `;
        this.querySelector("#collapse-dataset-information").addEventListener(
          "click",
          (event) => {
            const card = event.currentTarget.closest(".dataset-card");
            const collapsed = card.classList.toggle("is-collapsed");
            event.currentTarget.textContent = collapsed ? "+" : "−";
            event.currentTarget.setAttribute(
              "aria-expanded",
              String(!collapsed),
            );
            event.currentTarget.setAttribute(
              "aria-label",
              `${collapsed ? "Expand" : "Minimize"} dataset information`,
            );
            event.currentTarget.title = collapsed ? "Expand" : "Minimize";
          },
        );
        this.querySelector("#collapse-controls").addEventListener(
          "click",
          (event) => {
            const collapsed = this.classList.toggle("is-collapsed");
            event.currentTarget.textContent = collapsed ? "+" : "−";
            event.currentTarget.setAttribute(
              "aria-expanded",
              String(!collapsed),
            );
            event.currentTarget.setAttribute(
              "aria-label",
              `${collapsed ? "Expand" : "Minimize"} map controls`,
            );
            event.currentTarget.title = collapsed ? "Expand" : "Minimize";
          },
        );
        this.querySelector("#trait-select").addEventListener(
          "change",
          (event) => this.selectTrait(event.target.value, false),
        );
        this.querySelector("#basemap-select").addEventListener(
          "change",
          (event) => this.selectBasemap(event.target.value),
        );
        for (const name of ["mean", "cov", "aoa"]) {
          const eye = this.querySelector(`#${name}-visible`);
          setEye(eye, eye.dataset.visible === "true");
          eye.addEventListener("click", () => this.toggleLayer(name));
          const slider = this.querySelector(`#${name}-opacity`);
          slider.addEventListener("input", () =>
            this.setLayerOpacity(name, Number(slider.value)),
          );
          this.updateOpacityOutput(name);
        }
        this.querySelector("#cov-mode").addEventListener("change", () =>
          this.applyCovMode(),
        );
        for (const button of this.querySelectorAll(".help-button")) {
          button.addEventListener("click", () => this.toggleHelp(button));
        }
        this.helpOutsideHandler = (event) => {
          if (!event.target.closest?.(".help-button, .help-popover")) {
            this.closeHelp();
          }
        };
        this.helpKeyHandler = (event) => {
          if (event.key === "Escape") this.closeHelp(true);
        };
        document.addEventListener("pointerdown", this.helpOutsideHandler);
        document.addEventListener("keydown", this.helpKeyHandler);
      }

      toggleHelp(button) {
        const wasOpen = button.getAttribute("aria-expanded") === "true";
        this.closeHelp();
        if (wasOpen) return;
        const popover = this.querySelector(
          `#${button.getAttribute("aria-controls")}`,
        );
        popover.hidden = false;
        button.setAttribute("aria-expanded", "true");
        this.openHelpButton = button;
      }

      closeHelp(restoreFocus = false) {
        for (const button of this.querySelectorAll(".help-button")) {
          button.setAttribute("aria-expanded", "false");
          this.querySelector(
            `#${button.getAttribute("aria-controls")}`,
          ).hidden = true;
        }
        if (restoreFocus) this.openHelpButton?.focus();
        this.openHelpButton = null;
      }

      async configureScientificProjection() {
        const mapElement = window.eodashStore?.states?.mapEl?.value;
        await mapElement?.registerProjection?.(
          DATA_PROJECTION,
          DATA_PROJ4,
          DATA_EXTENT,
        );
        if (this.map.getView().getProjection().getCode() !== DATA_PROJECTION) {
          mapElement.projection = DATA_PROJECTION;
          await new Promise((resolve) => window.requestAnimationFrame(resolve));
          this.map = mapElement.map;
        }
        this.map.getTargetElement().style.background = "#d7e9ee";
        if (import.meta.env.DEV) {
          console.debug("[plant-traits] CRS flow", {
            authoritativeRasterCrs: DATA_PROJECTION,
            source: DATA_PROJECTION,
            contours: DATA_PROJECTION,
            map: this.map.getView().getProjection().getCode(),
            contourTransforms:
              this.map.getView().getProjection().getCode() === DATA_PROJECTION
                ? "none"
                : `${DATA_PROJECTION} -> ${this.map
                    .getView()
                    .getProjection()
                    .getCode()}`,
          });
        }
      }

      async useNativeRasterView(item) {
        const extent = item.properties?.["proj:bbox"];
        if (!extent) return;
        const oldView = this.map.getView();
        if (oldView.getProjection().getCode() !== DATA_PROJECTION) {
          await this.configureScientificProjection();
        }
        if (this.map.getView().getProjection().getCode() === DATA_PROJECTION) {
          this.map.getView().fit(extent, {
            size: this.map.getSize(),
            padding: [30, 30, 30, 30],
            maxZoom: 5,
          });
          return;
        }
        if (oldView.getProjection().getCode() === DATA_PROJECTION) return;
        this.map.setView(
          Promise.resolve({
            projection: DATA_PROJECTION,
            center: getCenter(extent),
            zoom: oldView.getZoom() ?? 1,
            rotation: oldView.getRotation(),
            extent,
            showFullExtent: true,
            smoothExtentConstraint: false,
          }),
        );
        await new Promise((resolve) => window.requestAnimationFrame(resolve));
        if (import.meta.env.DEV) {
          console.debug("[plant-traits] native raster view installed", {
            authoritativeRasterCrs: DATA_PROJECTION,
            map: this.map.getView().getProjection().getCode(),
            rasterExtent: extent,
            mapExtent: this.map.getView().getProjection().getExtent(),
            transformationsAppliedToContours: "none when map is EPSG:6933",
          });
        }
      }

      async installBasemaps() {
        for (const layer of this.map.getLayers().getArray()) {
          if (layer.get("id") === "osm" || layer.get("id") === "osm-standard") {
            layer.setVisible(false);
            layer.set("plantTraitBasemap", false);
          }
        }
        await installNaturalEarthBasemap(this.map, DATA_PROJECTION);
      }

      layerRow(name, title, visible, opacity, includeMode = false) {
        return `<div class="layer"><button id="${name}-visible" class="eye" type="button" data-name="${title}" data-visible="${visible}"></button><span class="layer-name">${title}</span>${
          includeMode
            ? `<div class="mode"><label for="cov-mode">Display</label><select id="cov-mode"><option value="overlay">Coloured overlay</option><option value="contours">Contour lines</option></select></div>`
            : ""
        }<div class="opacity"><label for="${name}-opacity">Opacity</label><input id="${name}-opacity" type="range" min="0" max="1" step="0.01" value="${opacity}"><output id="${name}-opacity-value"></output></div></div>`;
      }

      async selectBasemap(id) {
        if (id === "natural-earth") {
          await installNaturalEarthBasemap(this.map, DATA_PROJECTION);
        }
        for (const layer of this.map
          .getLayers()
          .getArray()
          .filter((candidate) => candidate.get("plantTraitBasemap"))) {
          layer.setVisible(layer.get("id") === "natural-earth-basemap");
        }
      }

      toggleLayer(name) {
        const button = this.querySelector(`#${name}-visible`);
        setEye(button, button.dataset.visible !== "true");
        if (name === "cov") this.applyCovMode();
        else this.layers?.[name].setVisible(button.dataset.visible === "true");
        this.updateLegends();
      }

      setLayerOpacity(name, opacity) {
        if (name === "cov") {
          this.layers?.cov.setOpacity(opacity);
          this.layers?.covContours.setOpacity(opacity);
        } else {
          this.layers?.[name].setOpacity(opacity);
        }
        this.updateOpacityOutput(name);
      }

      updateOpacityOutput(name) {
        const value = Number(this.querySelector(`#${name}-opacity`).value);
        this.querySelector(`#${name}-opacity-value`).value = `${Math.round(
          value * 100,
        )}%`;
      }

      async applyCovMode() {
        if (!this.layers) return;
        const visible =
          this.querySelector("#cov-visible").dataset.visible === "true";
        const mode = this.querySelector("#cov-mode").value;
        this.layers.cov.setVisible(visible && mode === "overlay");
        this.layers.covContours.setVisible(
          visible &&
            mode === "contours" &&
            this.layers.covContours.get("contoursLoaded"),
        );
        this.updateLegends();
        if (visible && mode === "contours") await this.ensureCovContours();
      }

      updateColorbar(element, ticksElement, palette, stops, formatter) {
        const minimum = stops[0];
        const span = stops.at(-1) - minimum;
        const positions = stops.map((stop) =>
          span ? ((stop - minimum) / span) * 100 : 0,
        );
        element.style.background = `linear-gradient(90deg, ${palette
          .map((color, index) => `${color} ${positions[index]}%`)
          .join(", ")})`;
        ticksElement.innerHTML = stops
          .map((stop) => `<span>${formatter(stop)}</span>`)
          .join("");
      }

      updateTraitLegend(item, stops) {
        const unit = item.products.mean.unit ?? "";
        this.querySelector("#trait-legend-title").textContent = `${item.title}${
          unit ? ` (${unit})` : ""
        }`;
        const colorbar = this.querySelector("#trait-colorbar");
        colorbar.setAttribute(
          "aria-label",
          `${item.title} colour scale from ${tickFormatter.format(
            stops[0],
          )} to ${tickFormatter.format(stops.at(-1))} ${unit}`.trim(),
        );
        this.updateColorbar(
          colorbar,
          this.querySelector("#trait-legend-ticks"),
          this.visualization.resolvedStyles.mean.palette,
          stops,
          (value) => tickFormatter.format(value),
        );
      }

      updateLegends() {
        if (!this.item) return;
        const covVisible =
          this.querySelector("#cov-visible").dataset.visible === "true";
        const covSection = this.querySelector("#cov-legend-section");
        covSection.hidden = !covVisible;
        if (covVisible) {
          const content = this.querySelector("#cov-legend-content");
          const mode = this.querySelector("#cov-mode").value;
          if (mode === "overlay") {
            content.innerHTML = `<div class="colorbar" id="cov-colorbar" role="img" aria-label="CoV colour scale"></div><div class="legend-ticks" id="cov-legend-ticks"></div>`;
            const style = this.visualization.resolvedStyles.cov;
            const paletteWithAlpha = style.palette.map((color, index) => {
              const alpha = Math.round(style.alpha[index] * 255)
                .toString(16)
                .padStart(2, "0");
              return `${color}${alpha}`;
            });
            this.updateColorbar(
              this.querySelector("#cov-colorbar"),
              this.querySelector("#cov-legend-ticks"),
              paletteWithAlpha,
              style.domain,
              (value) =>
                style.unit === "fraction"
                  ? `${tickFormatter.format(value * 100)}%`
                  : tickFormatter.format(value),
            );
          } else {
            content.innerHTML = `<div class="legend-key">${COV_CONTOUR_LEVELS.map(
              (level) =>
                `<span class="legend-key-item"><span class="line-swatch" style="color:${covColorForValue(
                  level,
                )}" aria-hidden="true"></span>${Math.round(
                  level * 100,
                )}%</span>`,
            ).join("")}</div>`;
          }
        }
        this.querySelector("#aoa-legend-section").hidden =
          this.querySelector("#aoa-visible").dataset.visible !== "true";
      }

      async ensureCovContours() {
        const layers = this.layers;
        const item = this.item;
        if (
          !layers ||
          layers.covContours.get("contoursLoaded") ||
          layers.covContours.get("contoursLoading")
        )
          return;
        layers.covContours.set("contoursLoading", true);
        const status = this.querySelector("#layer-status");
        status.textContent = "Loading the 16× COG overview for CoV contours…";
        try {
          const { populateCovContourLayer } = await import("./CovContours");
          const count = await populateCovContourLayer(
            layers.covContours,
            item,
            (done, total) => {
              status.textContent = `Calculating CoV contours ${done}/${total}…`;
            },
            this.map.getView().getProjection().getCode(),
          );
          if (this.layers !== layers) return;
          layers.covContours.setVisible(
            this.querySelector("#cov-visible").dataset.visible === "true" &&
              this.querySelector("#cov-mode").value === "contours",
          );
          status.textContent = `${count.toLocaleString()} contour paths · fixed levels 2, 3, 4, 6, 8, 12%`;
        } catch (error) {
          console.error("Failed to create CoV contours", error);
          status.textContent = `CoV contours failed: ${error.message}`;
        } finally {
          layers.covContours.set("contoursLoading", false);
        }
      }

      async selectTrait(itemId, fit) {
        const entry = this.canonical.items.find(
          (candidate) => candidate.id === itemId,
        );
        if (!entry) return;
        const generation = Symbol(itemId);
        this.selectionGeneration = generation;
        const select = this.querySelector("#trait-select");
        const status = this.querySelector("#layer-status");
        select.disabled = true;
        status.textContent = "Loading selected canonical STAC item…";
        try {
          const item = await loadCanonicalPlantTrait(entry, this.visualization);
          if (this.selectionGeneration !== generation) return;
          await this.useNativeRasterView(item);
          if (this.layers?.group) this.map.removeLayer(this.layers.group);
          if (this.pointerHandler)
            this.map.un("pointermove", this.pointerHandler);
          if (this.hoverLeaveHandler) {
            this.map
              .getViewport()
              .removeEventListener("pointerleave", this.hoverLeaveHandler);
          }
          this.item = item;
          this.layers = createPlantTraitLayerGroup(
            item,
            this.visualization,
            this.map.getView().getProjection().getCode(),
          );
          this.styleGeneration = generation;
          this.map.addLayer(this.layers.group);
          select.value = item.id;
          for (const name of ["mean", "aoa"]) {
            this.layers[name].setVisible(
              this.querySelector(`#${name}-visible`).dataset.visible === "true",
            );
            this.layers[name].setOpacity(
              Number(this.querySelector(`#${name}-opacity`).value),
            );
          }
          this.setLayerOpacity(
            "cov",
            Number(this.querySelector("#cov-opacity").value),
          );
          // Contour creation is intentionally detached from trait selection;
          // the map and controls remain interactive while the overview loads.
          void this.applyCovMode();
          this.updateTraitLegend(item, formatMeanStops(item));
          this.updateLegends();
          this.installHover(item);
          const url = new URL(window.location.href);
          url.searchParams.set("trait", item.id);
          window.history.replaceState(null, "", url);
          if (fit) fitItem(this.map, item);
          if (
            this.querySelector("#cov-visible").dataset.visible !== "true" ||
            this.querySelector("#cov-mode").value !== "contours"
          ) {
            status.textContent = "";
          }
          this.updateSampledMeanStyle(item, generation, 0);
        } catch (error) {
          console.error(`Failed to load ${itemId}`, error);
          status.textContent = `Trait loading failed: ${error.message}`;
        } finally {
          if (this.selectionGeneration === generation) select.disabled = false;
        }
      }

      installHover(item) {
        const hover = this.querySelector("#hover-value");
        const renderHover = ({ mean, cov, aoa, latitude, longitude }) => {
          const covIsFraction =
            this.visualization.resolvedStyles.cov.unit === "fraction";
          const meanText =
            mean === null
              ? "—"
              : `${mean.toPrecision(5)} ${
                  item.products.mean.unit ?? ""
                }`.trim();
          const covText =
            cov === null
              ? "—"
              : covIsFraction
                ? `${(cov * 100).toFixed(2)}%`
                : `${cov.toFixed(2)} ${item.products.cov.unit ?? ""}`.trim();
          const aoaText =
            aoa === null
              ? "—"
              : aoa === this.visualization.assetProducts.aoa.insideValue
                ? "Inside AoA"
                : aoa === this.visualization.assetProducts.aoa.outsideValue
                  ? "Outside AoA"
                  : aoa.toString();
          hover.innerHTML = `
            <div class="hover-row"><span class="hover-label">${
              item.title
            }</span>${meanText}</div>
            <div class="hover-row"><span class="hover-label">CoV</span>${covText}</div>
            <div class="hover-row"><span class="hover-label">AoA</span>${aoaText}</div>
            <div class="hover-row"><span class="hover-label">Latitude</span>${
              latitude === null ? "—" : `${latitude.toFixed(4)}°`
            }</div>
            <div class="hover-row"><span class="hover-label">Longitude</span>${
              longitude === null ? "—" : `${longitude.toFixed(4)}°`
            }</div>
          `;
        };
        const clearHover = () =>
          renderHover({
            mean: null,
            cov: null,
            aoa: null,
            latitude: null,
            longitude: null,
          });
        this.pointerHandler = (event) => {
          if (this.hoverFrame) window.cancelAnimationFrame(this.hoverFrame);
          const pixel = event.pixel.slice();
          const coordinate = event.coordinate.slice();
          this.hoverFrame = window.requestAnimationFrame(() => {
            const [longitude, latitude] = transform(
              coordinate,
              this.map.getView().getProjection(),
              "EPSG:4326",
            );
            renderHover({
              ...readPlantTraitValuesAtPixel(this.layers.mean, pixel, item),
              latitude: Number.isFinite(latitude) ? latitude : null,
              longitude: Number.isFinite(longitude) ? longitude : null,
            });
          });
        };
        this.hoverLeaveHandler = clearHover;
        this.map.on("pointermove", this.pointerHandler);
        this.map
          .getViewport()
          .addEventListener("pointerleave", this.hoverLeaveHandler);
      }

      updateSampledMeanStyle(item, generation, attempt) {
        if (this.styleGeneration !== generation || !this.layers?.mean) return;
        const stops = sampleMeanStyle(
          this.layers.mean,
          this.map,
          item,
          this.visualization.resolvedStyles.mean,
        );
        if (stops) {
          this.updateTraitLegend(item, stops);
          return;
        }
        if (attempt < 40)
          window.setTimeout(
            () => this.updateSampledMeanStyle(item, generation, attempt + 1),
            500,
          );
      }
    },
  );
}
