from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .config import load_config
from .runtime_paths import ensure_bundled_ffmpeg_on_path
from .transcribe import process_directory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="add_subs_to_videos",
        description="Recursively transcribe video files to .srt using whisper.cpp",
    )
    parser.add_argument("directory", type=Path, nargs="?", help="Video file or root directory to crawl for video files")
    parser.add_argument(
        "--model",
        default="medium",
        choices=["tiny", "base", "small", "medium", "large-v3"],
        help="Whisper model size (default: medium)",
    )
    parser.add_argument(
        "--language",
        default=None,
        metavar="LANG",
        help="Language code to pin (e.g. 'en'). Auto-detects if omitted.",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Number of CPU threads for whisper.cpp "
            "(default: all available cores; values above the core count are capped)"
        ),
    )
    parser.add_argument("--force", action="store_true", help="Re-transcribe even if .srt exists")
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress per-file progress and the tqdm bar; show only errors and the final summary",
    )
    verbosity.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show debug output including detected language per file",
    )
    return parser


def main() -> None:
    ensure_bundled_ffmpeg_on_path()
    parser = build_parser()
    cfg = load_config()
    if cfg:
        parser.set_defaults(**cfg)
    args = parser.parse_args()

    if args.directory is None:
        parser.error("directory is required (provide on the command line or set in config.toml)")
    args.directory = Path(args.directory).expanduser()

    if args.verbose:
        level = logging.DEBUG
    elif args.quiet:
        level = logging.WARNING
    else:
        level = logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )

    process_directory(
        args.directory,
        model_name=args.model,
        language=args.language,
        force=args.force,
        show_progress=not args.quiet,
        n_threads=args.threads,
    )


if __name__ == "__main__":
    main()
