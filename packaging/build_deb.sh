#!/usr/bin/env bash
# Builds add-subs-to-videos_<version>_amd64.deb
# Must be run on Ubuntu (x86-64). Requires sudo for apt/gem installs.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# --- Install build dependencies ---
sudo apt-get update -qq
sudo apt-get install -y cmake python3-pip ruby-rubygems librsvg2-bin

if ! command -v fpm &>/dev/null; then
    sudo gem install fpm
fi

# --- Read version from pyproject.toml ---
VERSION=$(python3 - <<'EOF'
import sys, pathlib
if sys.version_info >= (3, 11):
    import tomllib
    data = tomllib.loads(pathlib.Path("pyproject.toml").read_text())
else:
    # tomllib was added in 3.11; fall back to a simple grep
    import re
    text = pathlib.Path("pyproject.toml").read_text()
    data = {"project": {"version": re.search(r'version\s*=\s*"([^"]+)"', text).group(1)}}
print(data["project"]["version"])
EOF
)

echo "Building version: $VERSION"

# --- Compile and stage the Python package ---
STAGING="packaging/staging"
rm -rf "$STAGING"
mkdir -p "$STAGING"

# pip --target installs everything flat into STAGING (including the compiled .so).
# WHISPER_CUDA=1 can be set in the environment before calling this script for GPU builds.
pip3 install --target "$STAGING" .

# Remove the __pycache__ dirs — they're build-machine-specific
find "$STAGING" -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# --- Convert SVG icon to 128x128 PNG ---
rsvg-convert -w 128 -h 128 assets/icon.svg > packaging/icon.png

# Make the wrapper executable
chmod +x packaging/add_subs_to_videos

# --- Build the .deb ---
DEB_NAME="add-subs-to-videos_${VERSION}_amd64.deb"

fpm \
  -s dir \
  -t deb \
  --name add-subs-to-videos \
  --version "$VERSION" \
  --architecture amd64 \
  --depends ffmpeg \
  --depends "python3 (>= 3.12)" \
  --description "Recursive video-to-SRT transcription using whisper.cpp" \
  --url "https://github.com/simnim/add_subs_to_videos" \
  --license MIT \
  --package "$DEB_NAME" \
  --force \
  "$STAGING/=usr/lib/add_subs_to_videos/" \
  "packaging/add_subs_to_videos=/usr/bin/add_subs_to_videos" \
  "packaging/icon.png=/usr/share/pixmaps/add_subs_to_videos.png" \
  "assets/add_subs_to_videos.desktop=/usr/share/applications/add_subs_to_videos.desktop"

echo ""
echo "Done: $DEB_NAME"
echo ""
echo "Install with:"
echo "  sudo dpkg -i $DEB_NAME && sudo apt install -f"
