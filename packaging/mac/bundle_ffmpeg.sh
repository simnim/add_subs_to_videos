#!/usr/bin/env bash
# Copies ffmpeg/ffprobe (and their dylib dependencies) from Homebrew into
# <target_dir>/ffmpeg-bin/, rewriting the binaries' load commands so they
# resolve their dependencies relative to themselves (via @loader_path).
#
# This lets the bundled .app / CLI run transcription without the user having
# ffmpeg installed: `runtime_paths.ensure_bundled_ffmpeg_on_path()` puts
# <executable_dir>/ffmpeg-bin on PATH at startup.
#
# Usage: bundle_ffmpeg.sh <target_dir>
#   <target_dir> is the directory containing the app's main executable
#   (e.g. dist/Add Subs to Videos.app/Contents/MacOS, or dist/add_subs_to_videos)
#
# Requires: ffmpeg, ffprobe, dylibbundler (brew install ffmpeg dylibbundler)
set -euo pipefail

TARGET_DIR="${1:?Usage: bundle_ffmpeg.sh <target_dir>}"
BIN_DIR="$TARGET_DIR/ffmpeg-bin"
LIBS_DIR="$BIN_DIR/libs"

FFMPEG_SRC="$(command -v ffmpeg)"
FFPROBE_SRC="$(command -v ffprobe)"

mkdir -p "$LIBS_DIR"
cp "$FFMPEG_SRC" "$BIN_DIR/ffmpeg"
cp "$FFPROBE_SRC" "$BIN_DIR/ffprobe"
chmod +w "$BIN_DIR/ffmpeg" "$BIN_DIR/ffprobe"

# Dependency dylibs are copied into libs/ and referenced via @executable_path/.
# @executable_path always refers to the directory of the process's main
# executable (ffmpeg-bin/, since ffmpeg/ffprobe run as their own process's
# main executable) regardless of which file (ffmpeg itself, or one of the
# libs referencing another lib) does the loading -- so a single prefix works
# for both the top-level binaries and the inter-library references.
for bin in ffmpeg ffprobe; do
    dylibbundler -od -b -x "$BIN_DIR/$bin" -d "$LIBS_DIR" -p '@executable_path/libs/'
done

echo "Bundled ffmpeg/ffprobe into $BIN_DIR"
