from __future__ import annotations

import logging
import os
import sys
from pathlib import Path


def _prepend_to_path(directory: Path) -> None:
    if not directory.is_dir():
        return

    path = os.environ.get("PATH", "")
    if path.split(os.pathsep)[0] == str(directory):
        return  # already prepended; avoid duplicate entries if called more than once

    logging.debug("Prepending bundled ffmpeg directory to PATH: %s", directory)
    os.environ["PATH"] = os.pathsep.join([str(directory), path])


def ensure_bundled_ffmpeg_on_path() -> None:
    """Prepend a bundled ffmpeg/ffprobe directory to PATH, if one is available.

    Two bundling mechanisms are supported:
    - The macOS .app and CLI builds (see packaging/mac/) place a self-contained
      `ffmpeg-bin/` directory next to the executable when running from a
      PyInstaller bundle (`sys.frozen`), populated by
      `packaging/mac/bundle_ffmpeg.sh`.
    - The snap build (see snap/snapcraft.yaml) bundles ffmpeg via
      `stage-packages`, landing at `$SNAP/usr/bin`.

    `pywhispercpp` and `_probe_duration` both locate `ffmpeg`/`ffprobe` via
    `PATH`, so this lets the bundled app work without ffmpeg installed on the
    system.
    """
    if getattr(sys, "frozen", False):
        _prepend_to_path(Path(sys.executable).resolve().parent / "ffmpeg-bin")

    snap_dir = os.environ.get("SNAP")
    if snap_dir:
        _prepend_to_path(Path(snap_dir) / "usr" / "bin")
