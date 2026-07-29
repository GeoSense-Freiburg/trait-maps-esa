export const COV_CONTOUR_LEVELS = [0.02, 0.03, 0.04, 0.06, 0.08, 0.12];

const COV_COLOR_RAMP = [
  { stop: 0.02, color: "#a7d3ff" },
  { stop: 0.03, color: "#87c0ff" },
  { stop: 0.04, color: "#5aa5ff" },
  { stop: 0.06, color: "#2369d1" },
  { stop: 0.08, color: "#124f9f" },
  { stop: 0.12, color: "#083b8a" },
];

const hexToRgb = (hex) =>
  [1, 3, 5].map((index) => Number.parseInt(hex.slice(index, index + 2), 16));
const rgbToHex = (rgb) =>
  `#${rgb
    .map((value) => Math.round(value).toString(16).padStart(2, "0"))
    .join("")}`;

export const covColorForValue = (value) => {
  const clamped = Math.max(
    COV_CONTOUR_LEVELS[0],
    Math.min(COV_CONTOUR_LEVELS.at(-1), value),
  );
  const upperIndex = COV_COLOR_RAMP.findIndex(({ stop }) => stop >= clamped);
  if (upperIndex <= 0) return COV_COLOR_RAMP[0].color;
  const lower = COV_COLOR_RAMP[upperIndex - 1];
  const upper = COV_COLOR_RAMP[upperIndex];
  const fraction = (clamped - lower.stop) / (upper.stop - lower.stop);
  const lowerRgb = hexToRgb(lower.color);
  const upperRgb = hexToRgb(upper.color);
  return rgbToHex(
    lowerRgb.map(
      (channel, index) => channel + (upperRgb[index] - channel) * fraction,
    ),
  );
};
