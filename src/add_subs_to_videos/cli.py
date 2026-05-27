from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .device import detect_device, resolve_hf_token
from .transcribe import process_directory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crawl_srt",
        description="Recursively transcribe video files to .srt using WhisperX + speaker diarization",
    )
    parser.add_argument("directory", type=Path, help="Root directory to crawl for video files")
    parser.add_argument(
        "--model",
        required=True,
        choices=["tiny", "base", "small", "medium", "large-v3"],
        help="WhisperX model size",
    )
    parser.add_argument(
        "--language",
        default=None,
        metavar="LANG",
        help="Language code to pin (e.g. 'en'). Auto-detects if omitted.",
    )
    parser.add_argument(
        "--hf-token",
        default=None,
        dest="hf_token",
        metavar="TOKEN",
        help="HuggingFace token for diarization. Overrides HUGGINGFACE_TOKEN env var.",
    )
    parser.add_argument("--force", action="store_true", help="Re-transcribe even if .srt exists")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=16,
        dest="batch_size",
        help="Transcription batch size (default: 16; lower to 4-8 on CPU/MPS)",
    )
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress per-file progress; show only errors and the final summary",
    )
    verbosity.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show debug output including detected language per file",
    )
    return parser


def main() -> None:
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

    parser = build_parser()
    args = parser.parse_args()

    hf_token = resolve_hf_token(args.hf_token)
    device, compute_type = detect_device()
    logging.info("Device: %s, compute_type: %s", device, compute_type)

    process_directory(
        args.directory,
        model_name=args.model,
        device=device,
        compute_type=compute_type,
        hf_token=hf_token,
        language=args.language,
        force=args.force,
        batch_size=args.batch_size,
    )


if __name__ == "__main__":
    main()
