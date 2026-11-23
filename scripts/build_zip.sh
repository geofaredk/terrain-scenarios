#!/usr/bin/env bash
# Build the installable plugin ZIP: Plugins ▸ Manage and Install Plugins ▸ Install from ZIP.
# Usage: scripts/build_zip.sh [output-directory]   (default: the repo root)
#
# Only what the plugin needs at runtime goes in. Tests, the dev virtualenv, caches and the
# scratch profile stay out: a user installing this should not receive our test suite.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Resolved to an absolute path before anything below `cd`s elsewhere: a relative directory (e.g.
# `.`, meaning the caller's cwd) would otherwise be interpreted against the staging directory once
# the script has cd'd there, silently writing the ZIP where the EXIT trap then deletes it. `cd`ing
# into it here also makes a missing output directory fail immediately, with a clear reason.
OUT_DIR="$(cd "${1:-$ROOT}" && pwd)"
PACKAGE="terrain_scenarios"

if ! command -v zip >/dev/null 2>&1; then
  echo "build_zip.sh: the zip command is not installed" >&2
  exit 1
fi

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
    --exclude="*~" --exclude="*.swp" --exclude=".pytest_cache" \
    . | tar -x -C "$STAGE/$PACKAGE"

# The licence lives once, at the repo root where GitHub finds it, but plugins.qgis.org rejects a
# ZIP without a LICENSE inside the plugin folder, so it is copied into the staging copy here.
if [ ! -f "$ROOT/LICENSE" ]; then
  echo "build_zip.sh: LICENSE missing at the repo root" >&2
  exit 1
fi
cp "$ROOT/LICENSE" "$STAGE/$PACKAGE/LICENSE"

# __init__.py is what makes QGIS able to import the plugin at all. Checked on the staging copy,
# which also catches a tar that produced nothing.
test -f "$STAGE/$PACKAGE/__init__.py"  || { echo "build_zip.sh: __init__.py missing" >&2; exit 1; }
test -f "$STAGE/$PACKAGE/metadata.txt" || { echo "build_zip.sh: staging copy is incomplete" >&2; exit 1; }

rm -f "$ZIP"
(cd "$STAGE" && zip -q -r "$ZIP" "$PACKAGE")
echo "$ZIP"
