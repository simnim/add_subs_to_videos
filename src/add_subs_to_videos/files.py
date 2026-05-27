from __future__ import annotations

import sys
from pathlib import Path

VIDEO_EXTENSIONS: frozenset[str] = frozenset(
    {".mp4", ".mkv", ".avi", ".mov", ".m4v", ".webm", ".ts", ".flv"}
)


def find_videos(root: Path) -> list[Path]:
    if not root.is_dir():
        sys.exit(f"Error: '{root}' is not a directory")
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS)
