from __future__ import annotations

import os
import sys
from pathlib import Path


def ensure_bundled_ffmpeg_on_path() -> None:
    """Prepend the bundled ffmpeg/ffprobe directory to PATH, if running from a
    PyInstaller bundle that ships one.

    The macOS .app and CLI builds (see packaging/mac/) place a self-contained
    `ffmpeg-bin/` directory next to the executable, populated by
    `packaging/mac/bundle_ffmpeg.sh`. `pywhispercpp` and `_probe_duration` both
    locate `ffmpeg`/`ffprobe` via `PATH`, so this lets the bundled app work
    without ffmpeg installed on the system.
    """
    if not getattr(sys, "frozen", False):
        return

    ffmpeg_dir = Path(sys.executable).resolve().parent / "ffmpeg-bin"
    if not ffmpeg_dir.is_dir():
        return

    path = os.environ.get("PATH", "")
    if path.split(os.pathsep)[0] == str(ffmpeg_dir):
        return  # already prepended; avoid duplicate entries if called more than once

    os.environ["PATH"] = os.pathsep.join([str(ffmpeg_dir), path])
