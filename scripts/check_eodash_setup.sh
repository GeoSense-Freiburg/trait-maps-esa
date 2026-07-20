#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON="${PYTHON:-$REPO_ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="$(command -v python3)"
fi

for path in \
  stac_catalogs/stac_catalog_v1/catalog.json \
  eodash/config/asset-inventory.json \
  eodash/config/plant-trait-visualization.json \
  eodash/styles/plant-trait-mean.json \
  eodash/styles/plant-trait-cov.json \
  eodash/styles/plant-trait-aoa.json; do
  [[ -f "$path" ]] || { printf 'Required EO Dashboard file missing: %s\n' "$path" >&2; exit 1; }
done

"$PYTHON" scripts/check_static_stac_links.py
temporary_inventory="$(mktemp)"
trap 'rm -f -- "$temporary_inventory"' EXIT
"$PYTHON" scripts/build_eodash_asset_inventory.py --output "$temporary_inventory"
cmp --silent eodash/config/asset-inventory.json "$temporary_inventory" || {
  printf 'Asset inventory is stale. Run scripts/build_eodash_asset_inventory.py\n' >&2
  exit 1
}

printf 'Canonical static STAC and EO Dashboard configuration checks passed.\n'
