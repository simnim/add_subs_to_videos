from __future__ import annotations
from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("add_subs_to_videos")
except PackageNotFoundError:
    __version__ = "unknown"
