#!/usr/bin/env bash
# =============================================================================
# build-windows.sh — produces the Windows installer KnowledgeBank-Setup-<ver>.exe
#
# WHAT:  1. Downloads the official Windows Python 3.12 (NuGet "python" package,
#           published by the Python core team) and trims parts the engine
#           never uses (tests, IDLE, tkinter, headers).
#        2. Installs the engine's libraries (engine/requirements.txt) into that
#           Python as Windows (win_amd64) builds.
#        3. Builds the React interface and packages everything with
#           electron-builder into one NSIS installer.
#
# WHY:   The owner wants a normal double-click Windows app. Bundling a private
#        Python means he never installs Python, and versions are always exactly
#        the ones tested. Building on Linux (Claude's workspace) works because
#        every piece is either pure files or a pre-built Windows wheel.
#
# WHEN:  Run by the developer (Claude) for every release. NOT run by the owner.
#           bash tools/build-windows.sh
#        Output: app/release/KnowledgeBank-Setup-<version>.exe
#
# CONNECTED TO:
#        - engine/requirements.txt   → libraries bundled
#        - app/package.json "build"  → electron-builder settings: copies
#          engine/kb_engine → resources/engine/kb_engine and
#          app/build-resources/python → resources/python
#        - app/electron/main.cjs     → looks for those exact folders when
#          the app is installed (app.isPackaged)
# =============================================================================
set -euo pipefail

PY_VERSION="3.12.10"            # Windows Python bundled with the app
PY_TAG="3.12"                   # must match PY_VERSION's major.minor

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/app"
CACHE="$ROOT/.build-cache"       # downloads kept between builds (git-ignored)
PY_OUT="$APP/build-resources/python"

mkdir -p "$CACHE"

# --- 1. Windows Python --------------------------------------------------------
NUPKG="$CACHE/python.$PY_VERSION.nupkg"
if [ ! -f "$NUPKG" ]; then
  echo "==> Downloading Windows Python $PY_VERSION"
  curl -fsSL -o "$NUPKG" \
    "https://api.nuget.org/v3-flatcontainer/python/$PY_VERSION/python.$PY_VERSION.nupkg"
fi

echo "==> Unpacking Python"
rm -rf "$PY_OUT" "$CACHE/py-unpack"
mkdir -p "$CACHE/py-unpack"
unzip -q "$NUPKG" 'tools/*' -d "$CACHE/py-unpack"
mkdir -p "$(dirname "$PY_OUT")"
mv "$CACHE/py-unpack/tools" "$PY_OUT"

# Remove pieces the engine never uses (~25 MB smaller installer).
rm -rf "$PY_OUT/include" "$PY_OUT/libs" \
       "$PY_OUT/Lib/test" "$PY_OUT/Lib/idlelib" "$PY_OUT/Lib/tkinter" \
       "$PY_OUT/Lib/ensurepip" "$PY_OUT/Lib/turtledemo" \
       "$PY_OUT/Lib/site-packages/"*

# --- 2. Engine libraries (Windows builds) --------------------------------------
echo "==> Installing engine libraries for Windows"
# Any local Python with pip can do this; --platform makes pip fetch Windows
# wheels, --only-binary forbids compiling anything on this machine.
HOST_PY="${HOST_PY:-python3}"
"$HOST_PY" -m pip install --quiet --disable-pip-version-check \
  --target "$PY_OUT/Lib/site-packages" \
  --platform win_amd64 --python-version "$PY_TAG" --implementation cp \
  --only-binary=:all: \
  -r "$ROOT/engine/requirements.txt"
# pip puts Linux-style launcher scripts here; the engine doesn't use them.
rm -rf "$PY_OUT/Lib/site-packages/bin"
# Drop bytecode caches so the installer only contains source + binaries.
find "$PY_OUT" -name "__pycache__" -type d -prune -exec rm -rf {} +

# --- 3. Interface + installer ---------------------------------------------------
echo "==> Building interface and installer"
cd "$APP"
npm install --no-audit --no-fund
npm run dist:win

echo
echo "Done:"
ls -lh "$APP/release/"*.exe
