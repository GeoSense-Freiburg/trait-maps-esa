#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

CATALOG_JSON="stac_catalogs/stac_catalog_v1/catalog.json"
PIDS=()

if [[ ! -f "$CATALOG_JSON" ]]; then
  printf 'Canonical STAC catalog missing: %s\n' "$CATALOG_JSON" >&2
  exit 1
fi

for command in fuser grep npx npm setsid ss; do
  if ! command -v "$command" >/dev/null 2>&1; then
    printf 'Required command not found: %s\n' "$command" >&2
    exit 1
  fi
done

free_port() {
  local port="$1"
  local deadline
  local pid
  local -a listeners=()

  if ! ss -H -ltn "sport = :$port" | grep -q .; then
    return
  fi

  read -r -a listeners <<< "$(fuser -n tcp "$port" 2>/dev/null || true)"
  if ((${#listeners[@]} == 0)); then
    printf 'Port %s is in use, but its process is not visible to this user.\n' "$port" >&2
    ss -ltnp "sport = :$port" >&2 || true
    return 1
  fi

  printf 'Stopping stale process(es) on port %s:' "$port"
  for pid in "${listeners[@]}"; do
    printf ' %s' "$pid"
    if ! kill -TERM "$pid" 2>/dev/null; then
      printf '\nUnable to stop PID %s on port %s.\n' "$pid" "$port" >&2
      return 1
    fi
  done
  printf '\n'

  deadline=$((SECONDS + 5))
  while ss -H -ltn "sport = :$port" | grep -q .; do
    if ((SECONDS >= deadline)); then
      read -r -a listeners <<< "$(fuser -n tcp "$port" 2>/dev/null || true)"
      for pid in "${listeners[@]}"; do
        printf 'Process %s did not stop gracefully; sending SIGKILL.\n' "$pid" >&2
        kill -KILL "$pid" 2>/dev/null || true
      done
      break
    fi
    sleep 0.2
  done

  deadline=$((SECONDS + 2))
  while ss -H -ltn "sport = :$port" | grep -q .; do
    if ((SECONDS >= deadline)); then
      printf 'Port %s is still in use after stopping its previous listener.\n' "$port" >&2
      ss -ltnp "sport = :$port" >&2 || true
      return 1
    fi
    sleep 0.2
  done
}

for port in 3000 8000; do
  if ! free_port "$port"; then
    exit 1
  fi
done

cleanup() {
  local pid
  trap - EXIT INT TERM
  for pid in "${PIDS[@]}"; do
    # Each service runs in its own session, so this also stops npm/npx children.
    kill -- "-$pid" 2>/dev/null || true
  done
  for pid in "${PIDS[@]}"; do
    wait "$pid" 2>/dev/null || true
  done
}

trap cleanup EXIT
trap 'exit 130' INT TERM

# Port 8000 serves the canonical catalog and small viewer configuration files.
setsid npx http-server . -p 8000 --cors &
PIDS+=("$!")

# Port 3000 serves the viewer; strictPort prevents a silent fallback to 3001.
setsid npm --prefix eodash/viewer run dev &
PIDS+=("$!")

printf '\nEO Dashboard local services:\n'
printf 'Catalog:    http://localhost:8000/stac_catalogs/stac_catalog_v1/catalog.json\n'
printf 'Viewer:     http://localhost:3000/\n'
printf 'Explore:    http://localhost:3000/explore/?template=expert&trait=X144_mean_Shrub_Tree_Grass_1km\n'
printf 'COG test:   http://localhost:3000/?debug=remote-cog\n\n'
printf 'Press Ctrl+C to stop all services.\n'

wait -n "${PIDS[@]}"
