#!/usr/bin/env bash
# Builds Add Subs to Videos-<version>.dmg
# Must be run on macOS. Requires: librsvg, create-dmg, ffmpeg, dylibbundler
# (brew install librsvg create-dmg ffmpeg dylibbundler)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

VERSION=$(cat VERSION)
echo "Building version: $VERSION"
export APP_VERSION="$VERSION"

# Convert SVG icon to .icns
echo "Converting icon..."
ICON_PNG="/tmp/add_subs_icon_1024.png"
ICONSET="/tmp/add_subs_icon.iconset"
rsvg-convert -w 1024 -h 1024 assets/icon.svg > "$ICON_PNG"
rm -rf "$ICONSET"
mkdir "$ICONSET"
for SIZE in 16 32 64 128 256 512; do
    sips -z $SIZE $SIZE "$ICON_PNG" --out "$ICONSET/icon_${SIZE}x${SIZE}.png" >/dev/null
    DOUBLE=$((SIZE * 2))
    sips -z $DOUBLE $DOUBLE "$ICON_PNG" --out "$ICONSET/icon_${SIZE}x${SIZE}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o assets/icon.icns
echo "Icon created: assets/icon.icns"

# Install PyInstaller if not already present
if ! uv run --extra gui pyinstaller --version &>/dev/null 2>&1; then
    uv add --dev pyinstaller
fi

# Build .app bundle
echo "Building .app bundle..."
uv run --extra gui pyinstaller \
    packaging/mac/add_subs_to_videos.spec \
    --distpath dist \
    --workpath build/pyinstaller \
    --noconfirm

APP_PATH="dist/Add Subs to Videos.app"
CLI_DIR="dist/add_subs_to_videos"
if [ ! -d "$APP_PATH" ]; then
    echo "Error: .app bundle not found at $APP_PATH"
    exit 1
fi
if [ ! -d "$CLI_DIR" ]; then
    echo "Error: CLI bundle not found at $CLI_DIR"
    exit 1
fi
echo "App bundle built: $APP_PATH"
echo "CLI bundle built: $CLI_DIR"

# Bundle a self-contained ffmpeg/ffprobe (with their dylib deps) into both the
# .app and the CLI bundle, so neither needs ffmpeg installed on the system.
echo "Bundling ffmpeg..."
bash packaging/mac/bundle_ffmpeg.sh "$APP_PATH/Contents/MacOS"
bash packaging/mac/bundle_ffmpeg.sh "$CLI_DIR"

# Stage everything for the DMG into one directory
DMG_STAGING="build/dmg_staging"
rm -rf "$DMG_STAGING"
mkdir -p "$DMG_STAGING"
cp -R "$APP_PATH" "$DMG_STAGING/Add Subs to Videos.app"
cp -R "$CLI_DIR" "$DMG_STAGING/add_subs_to_videos"
cp "packaging/mac/Install CLI.command" "$DMG_STAGING/Install CLI.command"
chmod +x "$DMG_STAGING/Install CLI.command"

# Build .dmg
echo "Building .dmg..."
DMG_NAME="Add Subs to Videos-${VERSION}.dmg"
rm -f "$DMG_NAME"
create-dmg \
    --volname "Add Subs to Videos" \
    --window-pos 200 120 \
    --window-size 800 400 \
    --icon-size 100 \
    --icon "Add Subs to Videos.app" 200 185 \
    --hide-extension "Add Subs to Videos.app" \
    --app-drop-link 600 185 \
    --icon "Install CLI.command" 400 300 \
    --icon "add_subs_to_videos" 600 300 \
    "$DMG_NAME" \
    "$DMG_STAGING"

echo ""
echo "Done: $DMG_NAME"
echo ""
echo "Test with:"
echo "  open \"$DMG_NAME\""
