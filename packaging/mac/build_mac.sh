#!/usr/bin/env bash
# Builds Add Subs to Videos-<version>.dmg
# Must be run on macOS. Requires: librsvg, create-dmg (brew install librsvg create-dmg)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

# Read version from pyproject.toml
VERSION=$(python3 - <<'EOF'
import sys, pathlib
if sys.version_info >= (3, 11):
    import tomllib
    data = tomllib.loads(pathlib.Path("pyproject.toml").read_text())
else:
    import re
    text = pathlib.Path("pyproject.toml").read_text()
    data = {"project": {"version": re.search(r'version\s*=\s*"([^"]+)"', text).group(1)}}
print(data["project"]["version"])
EOF
)
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
if ! uv run pyinstaller --version &>/dev/null 2>&1; then
    uv add --dev pyinstaller
fi

# Build .app bundle
echo "Building .app bundle..."
uv run pyinstaller \
    packaging/mac/add_subs_to_videos.spec \
    --distpath dist \
    --workpath build/pyinstaller \
    --noconfirm

APP_PATH="dist/Add Subs to Videos.app"
CLI_PATH="dist/add_subs_to_videos"
if [ ! -d "$APP_PATH" ]; then
    echo "Error: .app bundle not found at $APP_PATH"
    exit 1
fi
if [ ! -e "$CLI_PATH" ]; then
    echo "Error: CLI binary not found at $CLI_PATH"
    exit 1
fi
echo "App bundle built: $APP_PATH"
echo "CLI binary built: $CLI_PATH"

# Stage the CLI binary + installer helper for the DMG
DMG_STAGING="build/dmg_staging"
rm -rf "$DMG_STAGING"
mkdir -p "$DMG_STAGING"
cp -R "$CLI_PATH" "$DMG_STAGING/add_subs_to_videos"
cp "packaging/mac/Install CLI.command" "$DMG_STAGING/Install CLI.command"
chmod +x "$DMG_STAGING/add_subs_to_videos" "$DMG_STAGING/Install CLI.command"

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
    "$APP_PATH" \
    "$DMG_STAGING/Install CLI.command" \
    "$DMG_STAGING/add_subs_to_videos"

echo ""
echo "Done: $DMG_NAME"
echo ""
echo "Test with:"
echo "  open \"$DMG_NAME\""
