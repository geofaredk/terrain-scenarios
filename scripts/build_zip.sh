#!/usr/bin/env bash
# Build the installable plugin ZIP: Plugins ▸ Manage and Install Plugins ▸ Install from ZIP.
# Usage: scripts/build_zip.sh [output-directory]   (default: the repo root)
#
# Only what the plugin needs at runtime goes in. Tests, the dev virtualenv, caches and the
# scratch profile stay out: a user installing this should not receive our test suite.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${1:-$ROOT}"
PACKAGE="terrain_sketch"

# metadata.txt is what QGIS reads to list the plugin; without it the ZIP installs as nothing.
# Checked before the version is read, so a missing file reports itself rather than a sed error.
if [ ! -f "$ROOT/$PACKAGE/metadata.txt" ]; then
  echo "build_zip.sh: $PACKAGE/metadata.txt missing" >&2
  exit 1
fi
VERSION="$(sed -n 's/^version=//p' "$ROOT/$PACKAGE/metadata.txt" | head -1)"
if [ -z "$VERSION" ]; then
  echo "build_zip.sh: no version= in $PACKAGE/metadata.txt" >&2
  exit 1
fi
ZIP="$OUT_DIR/${PACKAGE}-${VERSION}.zip"

# Build from a clean staging copy so nothing local (a stray .pyc, an editor swap file) ships.
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/$PACKAGE"
tar -c -C "$ROOT/$PACKAGE" \
    --exclude="__pycache__" --exclude="*.pyc" --exclude="*.pyo" --exclude=".DS_Store" \
    . | tar -x -C "$STAGE/$PACKAGE"

# __init__.py is what makes QGIS able to import the plugin at all. Checked on the staging copy,
# which also catches a tar that produced nothing.
test -f "$STAGE/$PACKAGE/__init__.py"  || { echo "build_zip.sh: __init__.py missing" >&2; exit 1; }
test -f "$STAGE/$PACKAGE/metadata.txt" || { echo "build_zip.sh: staging copy is incomplete" >&2; exit 1; }

rm -f "$ZIP"
(cd "$STAGE" && zip -q -r "$ZIP" "$PACKAGE")
echo "$ZIP"
