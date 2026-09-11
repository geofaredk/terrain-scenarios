#!/usr/bin/env bash
# Run the test suite with the Python interpreter bundled in QGIS 4 (macOS app bundle).
# Usage: scripts/test.sh [pytest args]   e.g. scripts/test.sh tests/core -k mask
# Override the app location with QGIS_APP=/Applications/Other-QGIS.app scripts/test.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
QGIS_APP="${QGIS_APP:-/Applications/QGIS-final-4_2_2.app}"
B="$QGIS_APP/Contents"
PY="$B/MacOS/python3.12"
export PYTHONHOME="$B/Resources"
export PYTHONPATH="$ROOT:$B/Resources/python3.12:$B/Resources/python3.12/site-packages:$B/Resources/python3.12/lib-dynload:$ROOT/.devdeps"
export PROJ_DATA="$B/Resources/qgis/proj"
export QGIS_PREFIX_PATH="$QGIS_APP"
export QT_PLUGIN_PATH="$B/PlugIns"
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"
if [ ! -d "$ROOT/.devdeps/pytest" ]; then
  if ! "$PY" -m pip install -q --disable-pip-version-check --target "$ROOT/.devdeps" pytest; then
    echo "scripts/test.sh: could not install pytest into .devdeps/ (the first run needs a network connection)" >&2
    exit 1
  fi
fi
cd "$ROOT"
exec "$PY" -m pytest "$@"
