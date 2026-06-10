from __future__ import annotations

import sys
from pathlib import Path

VIDEO_EXTENSIONS: frozenset[str] = frozenset(
    {".mp4", ".mkv", ".avi", ".mov", ".m4v", ".webm", ".ts", ".flv"}
)


def find_videos(root: Path) -> list[Path]:
    if root.is_dir():
        return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS)
    if root.is_file():
        if root.suffix.lower() in VIDEO_EXTENSIONS:
            return [root]
        sys.exit(f"Error: '{root}' is not a supported video file")
    sys.exit(f"Error: '{root}' does not exist")


def format_size_mb(size_bytes: int) -> str:
    mb = size_bytes / (1024 * 1024)
    if mb < 10:
        return f"{mb:.1f}M"
    return f"{round(mb)}M"


def build_video_tree(root: Path) -> str:
    if root.is_file():
        return f"[{format_size_mb(root.stat().st_size):>4}]  {root.name}"

    videos = find_videos(root)
    if not videos:
        return ""

    tree: dict = {"dirs": {}, "files": {}}
    for video in videos:
        node = tree
        parts = video.relative_to(root).parts
        for part in parts[:-1]:
            node = node["dirs"].setdefault(part, {"dirs": {}, "files": {}})
        node["files"][parts[-1]] = video.stat().st_size

    def dir_size(node: dict) -> int:
        return sum(node["files"].values()) + sum(dir_size(child) for child in node["dirs"].values())

    root_name = root.name or str(root)
    lines = [f"[{format_size_mb(dir_size(tree)):>4}]  {root_name}/"]

    def render_children(node: dict, prefix: str) -> None:
        entries = sorted(list(node["dirs"]) + list(node["files"]))
        for i, entry in enumerate(entries):
            is_last = i == len(entries) - 1
            connector = "└── " if is_last else "├── "
            child_prefix = prefix + ("    " if is_last else "│   ")
            if entry in node["dirs"]:
                child = node["dirs"][entry]
                lines.append(f"{prefix}{connector}[{format_size_mb(dir_size(child)):>4}]  {entry}/")
                render_children(child, child_prefix)
            else:
                size = node["files"][entry]
                lines.append(f"{prefix}{connector}[{format_size_mb(size):>4}]  {entry}")

    render_children(tree, "")
    return "\n".join(lines)
