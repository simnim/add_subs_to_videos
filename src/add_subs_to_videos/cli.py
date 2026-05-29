from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .transcribe import process_directory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="add_subs_to_videos",
        description="Recursively transcribe video files to .srt using whisper.cpp",
    )
    parser.add_argument("directory", type=Path, help="Root directory to crawl for video files")
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
    parser = build_parser()
    args = parser.parse_args()

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
    )


if __name__ == "__main__":
    main()
