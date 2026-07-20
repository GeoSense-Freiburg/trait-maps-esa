import WebGLTileLayerRenderer from "ol/renderer/webgl/TileLayer.js";

const installed = Symbol("nativeAoACrossShaderInstalled");

const hexToRgb = (hex) => {
  const match = /^#([0-9a-f]{6})$/i.exec(hex ?? "");
  if (!match) return [1, 0.427, 0];
  return [0, 2, 4].map(
    (offset) => Number.parseInt(match[1].slice(offset, offset + 2), 16) / 255,
  );
};

class NativeAoATileRenderer extends WebGLTileLayerRenderer {
  constructor(layer, options) {
    super(layer, options);
    this.nativeShaderOptions = options;
  }

  reset() {
    // WebGLTileLayer resets its renderer when its parsed style changes. The
    // layer's fallback style is transparent, so accepting that reset silently
    // replaced the native AoA shader with a fully transparent fragment shader.
    super.reset(this.nativeShaderOptions);
  }

  renderTile(
    tileTexture,
    tileTransform,
    frameState,
    renderExtent,
    tileResolution,
    tileSize,
    tileOrigin,
    tileExtent,
    depth,
    gutter,
    alpha,
  ) {
    const tileCoord = tileTexture.tile.tileCoord;
    const textureOrigin = [
      tileOrigin[0] +
        tileCoord[1] * tileSize[0] * tileResolution -
        gutter * tileResolution,
      tileOrigin[1] -
        tileCoord[2] * tileSize[1] * tileResolution +
        gutter * tileResolution,
    ];
    this.helper.setUniformFloatVec2("u_textureOrigin", textureOrigin);
    super.renderTile(
      tileTexture,
      tileTransform,
      frameState,
      renderExtent,
      tileResolution,
      tileSize,
      tileOrigin,
      tileExtent,
      depth,
      gutter,
      alpha,
    );
  }
}

const makeVertexShader = (trait) => `
  attribute vec2 a_textureCoord;
  uniform mat4 u_tileTransform;
  uniform float u_texturePixelWidth;
  uniform float u_texturePixelHeight;
  uniform float u_textureResolution;
  uniform float u_depth;
  uniform vec2 u_textureOrigin;

  varying vec2 v_textureCoord;
  varying vec2 v_localMapCoord;
  varying vec2 v_sourceCoord;

  vec2 webMercatorToEpsg6933(vec2 mapCoord) {
    const float earthRadius = 6378137.0;
    const float eccentricitySquared = 0.0066943799901413165;
    const float eccentricity = 0.08181919084262149;
    const float ceaScale = 0.8667510025721987;
    float longitude = mapCoord.x / earthRadius;
    float latitude = 2.0 * atan(exp(mapCoord.y / earthRadius)) - 1.5707963267948966;
    float sinLatitude = sin(latitude);
    float q = (1.0 - eccentricitySquared) * (
      sinLatitude / (1.0 - eccentricitySquared * sinLatitude * sinLatitude) -
      log(
        (1.0 - eccentricity * sinLatitude) /
        (1.0 + eccentricity * sinLatitude)
      ) / (2.0 * eccentricity)
    );
    return vec2(
      earthRadius * ceaScale * longitude,
      earthRadius * q / (2.0 * ceaScale)
    );
  }

  void main() {
    v_textureCoord = a_textureCoord;
    v_localMapCoord = vec2(
      u_texturePixelWidth * u_textureResolution * v_textureCoord.x,
      -u_texturePixelHeight * u_textureResolution * v_textureCoord.y
    );
    // Projection is evaluated four times per tile (at the vertices), rather
    // than for every screen fragment. At zooms where native crosses are
    // resolvable, linear interpolation within a tile is sub-pixel accurate.
    v_sourceCoord = ${
      trait?.map_epsg === 6933
        ? "u_textureOrigin + v_localMapCoord"
        : "webMercatorToEpsg6933(u_textureOrigin + v_localMapCoord)"
    };
    gl_Position = u_tileTransform * vec4(a_textureCoord, u_depth, 1.0);
  }
`;

const makeFragmentShader = (trait, aoaStyle = {}) => {
  if (
    trait?.source_epsg !== 6933 ||
    trait?.source_extent?.length !== 4 ||
    trait?.shape?.length !== 2
  ) {
    throw new Error(
      "Native AoA cross shader requires an EPSG:6933 source extent and raster shape",
    );
  }
  const [minX, , , maxY] = trait.source_extent;
  const [height, width] = trait.shape;
  const pixelWidth = (trait.source_extent[2] - minX) / width;
  const pixelHeight = (maxY - trait.source_extent[1]) / height;
  const [red, green, blue] = hexToRgb(aoaStyle.cross_color);
  const crossOpacity = Math.min(1, Math.max(0, aoaStyle.cross_alpha ?? 0.95));
  const overviewOpacity = crossOpacity * 0.68;

  return `
  #ifdef GL_FRAGMENT_PRECISION_HIGH
  precision highp float;
  #else
  precision mediump float;
  #endif

  varying vec2 v_textureCoord;
  varying vec2 v_localMapCoord;
  varying vec2 v_sourceCoord;
  uniform vec4 u_renderExtent;
  uniform float u_transitionAlpha;
  uniform float u_texturePixelWidth;
  uniform float u_texturePixelHeight;
  uniform float u_textureResolution;
  uniform float u_resolution;
  uniform sampler2D u_tileTextures[1];

  void main() {
    // OpenLayers uses a zero-width render extent as the "no clipping" sentinel.
    // Match its generated shaders; treating that sentinel as a real extent
    // discarded every AoA fragment.
    if (
      abs(u_renderExtent.x - u_renderExtent.z) > 0.0 &&
      (
        v_localMapCoord.x < u_renderExtent.x ||
        v_localMapCoord.y < u_renderExtent.y ||
        v_localMapCoord.x > u_renderExtent.z ||
        v_localMapCoord.y > u_renderExtent.w
      )
    ) {
      discard;
    }

    // Band 3 is the outside-AoA flag: 0 = inside, 1 = outside. Its lower
    // resolution overviews were averaged, so fractional values are possible.
    float outsideAoA = texture2D(u_tileTextures[0], v_textureCoord).b;

    vec2 nativeGridPosition = vec2(
      (v_sourceCoord.x - ${minX}) / ${pixelWidth},
      (${maxY} - v_sourceCoord.y) / ${pixelHeight}
    );
    vec2 cellPosition = fract(nativeGridPosition);

    // Below two screen pixels a native 1-km X cannot be resolved. Render a
    // compact warning fill instead of producing an aliased false grid.
    float screenPixelsPerNativeCell = ${Math.min(
      pixelWidth,
      pixelHeight,
    )} / u_resolution;
    if (screenPixelsPerNativeCell < 2.0) {
      if (outsideAoA <= 0.0) {
        discard;
      }
      float overviewAlpha = ${overviewOpacity} * clamp(outsideAoA * 4.0, 0.25, 1.0);
      vec4 overviewColor = vec4(${red}, ${green}, ${blue}, overviewAlpha);
      overviewColor.rgb *= overviewColor.a;
      gl_FragColor = overviewColor * u_transitionAlpha;
      return;
    }

    if (outsideAoA < 0.5) {
      discard;
    }

    // The 10% inset keeps every X strictly inside one native AoA cell.
    vec2 crossPosition = (cellPosition - 0.5) / 0.8 + 0.5;
    if (
      crossPosition.x < 0.0 || crossPosition.x > 1.0 ||
      crossPosition.y < 0.0 || crossPosition.y > 1.0
    ) {
      discard;
    }

    float diagonalDistance = min(
      abs(crossPosition.x - crossPosition.y),
      abs(crossPosition.x + crossPosition.y - 1.0)
    );
    float screenPixelsPerCell = screenPixelsPerNativeCell;
    float lineHalfWidth = max(
      0.055,
      0.75 / max(screenPixelsPerCell, 1.0)
    );
    float crossAlpha = 1.0 - smoothstep(
      lineHalfWidth,
      lineHalfWidth + 0.025,
      diagonalDistance
    );
    if (crossAlpha <= 0.0) {
      discard;
    }

    vec4 color = vec4(${red}, ${green}, ${blue}, ${crossOpacity} * crossAlpha);
    color.rgb *= color.a;
    gl_FragColor = color * u_transitionAlpha;
  }
`;
};

export const installNativeAoACrossShader = (layer, trait, aoaStyle) => {
  if (!layer || layer[installed]) return false;
  layer[installed] = true;

  const source = layer.getSource?.();
  if (source) {
    // A categorical mask must never be interpolated between 0 and 1.
    source.interpolate = false;
    if (source.tileOptions) {
      source.tileOptions.interpolate = false;
      // Avoid fading an old tile grid over the current map position. The
      // default 250 ms transition made crosses appear to lag and then snap.
      source.tileOptions.transition = 0;
    }
  }

  layer.createRenderer = function createNativeAoARenderer() {
    return new NativeAoATileRenderer(this, {
      vertexShader: makeVertexShader(trait),
      fragmentShader: makeFragmentShader(trait, aoaStyle),
      uniforms: {},
      cacheSize: this.getCacheSize(),
    });
  };
  layer.clearRenderer();
  layer.changed();
  layer.set("aoaNativeCrossShader", true);
  return true;
};
