export const TRAIT_STATUS_PROPERTY = "trait_map:product_status";

const normalizeStatusValue = (value) => {
  if (typeof value !== "string") return null;
  const normalized = value
    .trim()
    .toLowerCase()
    .replaceAll("_", "-")
    .replace(/\s+/g, "-");
  return normalized || null;
};

const statusLabel = (normalized) => {
  if (!normalized) return "Unknown";
  return normalized
    .split("-")
    .filter(Boolean)
    .map((word) => word[0].toUpperCase() + word.slice(1))
    .join(" ");
};

export const getTraitStatus = (item) => {
  const value = item?.properties?.[TRAIT_STATUS_PROPERTY];
  const normalized = normalizeStatusValue(value);
  return {
    value: typeof value === "string" ? value : null,
    normalized,
    label: statusLabel(normalized),
    isExperimental: normalized === "experimental",
  };
};

export const isExperimentalTrait = (item) =>
  getTraitStatus(item).isExperimental;
