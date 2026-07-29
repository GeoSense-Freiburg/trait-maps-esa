import { createEodash } from "@eodash/eodash";
import light from "./templates/light";
import expert from "./templates/expert";
import compare from "./templates/compare";
import { stacEndpoint } from "./plantTraits/canonicalCatalog";

const isRemoteCogDiagnostic =
  new URL(window.location.href).searchParams.get("debug") === "remote-cog";

if (isRemoteCogDiagnostic) {
  await import("./debug/remote-cog-test");
} else {
  await import("./plantTraits/PlantTraitControls");
  const defaultView = new URL(window.location.href);
  if (!defaultView.searchParams.has("template")) {
    defaultView.pathname = `${import.meta.env.BASE_URL}explore/`.replace(
      /\/+/g,
      "/",
    );
    defaultView.searchParams.set("template", "expert");
    window.history.replaceState(null, "", defaultView);
  }
}

// The EO Dashboard runtime imports this module as its configuration even on
// the diagnostic URL. Always return a complete configuration so the detached
// dashboard bootstrap does not emit a misleading missing-endpoint error.
const application = createEodash({
  id: "plant-traits",
  stacEndpoint,
  options: { useSubCode: false },
  brand: {
    name: "Global Plant Trait Maps Explorer",
    logo: `${import.meta.env.BASE_URL}logo_gtm.png`,
    errorMessage: "The plant-trait viewer could not be initialized.",
    footerText: "Canonical STAC metadata · Zenodo raster assets",
    theme: {
      colors: {
        primary: "#004170",
        secondary: "#004170",
        background: "#fff",
        surface: "#fff",
      },
    },
  },
  templates: { light, expert, compare },
});

export default application;
