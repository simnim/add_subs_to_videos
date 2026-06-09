#!/usr/bin/env bash
# Double-click to install the `add_subs_to_videos` CLI to /usr/local/bin.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$DIR/add_subs_to_videos"
DEST="/usr/local/bin/add_subs_to_videos"

if [ ! -x "$SRC" ]; then
    echo "Error: CLI binary not found next to this script ($SRC)"
    read -n 1 -s -r -p "Press any key to close..."
    exit 1
fi

echo "Installing CLI to $DEST (you may be asked for your password)..."
sudo mkdir -p "$(dirname "$DEST")"
sudo ln -sf "$SRC" "$DEST"
sudo chmod +x "$SRC"

echo ""
echo "Done! Open a new terminal and run: add_subs_to_videos --help"
read -n 1 -s -r -p "Press any key to close..."
