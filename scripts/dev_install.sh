#!/usr/bin/env bash
# Link the plugin into a QGIS 4 profile for development (macOS), then enable "Terrain Sketch"
# in Plugins ▸ Manage and Install Plugins ▸ Installed. Usage: scripts/dev_install.sh [profile]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROFILE="${1:-default}"
PLUGINS="$HOME/Library/Application Support/QGIS/QGIS4/profiles/$PROFILE/python/plugins"
mkdir -p "$PLUGINS"
if [ -e "$PLUGINS/terrain_sketch" ] && [ ! -L "$PLUGINS/terrain_sketch" ]; then
  echo "$PLUGINS/terrain_sketch exists and is not a link; move it away first." >&2
  exit 1
fi
ln -sfn "$ROOT/terrain_sketch" "$PLUGINS/terrain_sketch"
echo "Linked $PLUGINS/terrain_sketch -> $ROOT/terrain_sketch"
