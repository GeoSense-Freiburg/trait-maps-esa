export const COV_CONTOUR_LEVELS = [0.02, 0.03, 0.04, 0.06, 0.08, 0.12];

const COV_COLOR_RAMP = [
  { stop: 0, color: "#f7fbff" },
  { stop: 0.3, color: "#2b8cbe" },
  { stop: 0.65, color: "#d84a9b" },
  { stop: 1, color: "#b2182b" },
];

const hexToRgb = (hex) =>
  [1, 3, 5].map((index) => Number.parseInt(hex.slice(index, index + 2), 16));
const rgbToHex = (rgb) =>
  `#${rgb
    .map((value) => Math.round(value).toString(16).padStart(2, "0"))
    .join("")}`;

export const covColorForValue = (value) => {
  const minimum = COV_CONTOUR_LEVELS[0];
  const maximum = COV_CONTOUR_LEVELS.at(-1);
  const normalized = Math.max(
    0,
    Math.min(1, (value - minimum) / (maximum - minimum)),
  );
  const upperIndex = COV_COLOR_RAMP.findIndex(({ stop }) => stop >= normalized);
  if (upperIndex <= 0) return COV_COLOR_RAMP[0].color;
  const lower = COV_COLOR_RAMP[upperIndex - 1];
  const upper = COV_COLOR_RAMP[upperIndex];
  const fraction = (normalized - lower.stop) / (upper.stop - lower.stop);
  const lowerRgb = hexToRgb(lower.color);
  const upperRgb = hexToRgb(upper.color);
  return rgbToHex(
    lowerRgb.map(
      (channel, index) => channel + (upperRgb[index] - channel) * fraction,
    ),
  );
};
