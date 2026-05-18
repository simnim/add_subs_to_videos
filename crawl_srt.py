from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import whisperx

VIDEO_EXTENSIONS: frozenset[str] = frozenset(
    {".mp4", ".mkv", ".avi", ".mov", ".m4v", ".webm", ".ts", ".flv"}
)


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
    return parser


def detect_device() -> tuple[str, str]:
    """Returns (device, compute_type). Priority: CUDA > MPS > CPU."""
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda", "float16"
        if torch.backends.mps.is_available():
            # MPS does not support float16 in ctranslate2
            return "mps", "float32"
    except ImportError:
        pass
    return "cpu", "int8"


def resolve_hf_token(cli_token: str | None) -> str:
    token = cli_token or os.environ.get("HUGGINGFACE_TOKEN", "")
    if not token:
        sys.exit(
            "Error: HuggingFace token required for diarization.\n"
            "Set HUGGINGFACE_TOKEN env var or pass --hf-token TOKEN.\n"
            "Note: you must also accept the pyannote model license at "
            "https://huggingface.co/pyannote/speaker-diarization-3.1"
        )
    return token


def find_videos(root: Path) -> list[Path]:
    if not root.is_dir():
        sys.exit(f"Error: '{root}' is not a directory")
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS)


def format_srt_timestamp(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def segments_to_srt(segments: list[dict]) -> str:
    lines: list[str] = []
    index = 1
    for seg in segments:
        text = seg["text"].strip()
        if not text:
            continue
        start_ts = format_srt_timestamp(seg["start"])
        end_ts = format_srt_timestamp(seg["end"])
        speaker = seg.get("speaker", "UNKNOWN")
        lines.append(str(index))
        lines.append(f"{start_ts} --> {end_ts}")
        lines.append(f"{speaker}: {text}")
        lines.append("")
        index += 1
    return "\n".join(lines)


def transcribe_video(
    video_path: Path,
    *,
    model: whisperx.Whisper,
    device: str,
    hf_token: str,
    language: str | None,
    batch_size: int,
) -> str:
    audio = whisperx.load_audio(str(video_path))

    result = model.transcribe(audio, batch_size=batch_size, language=language)
    detected_lang = result["language"]
    logging.debug("  detected language: %s", detected_lang)

    align_model, metadata = whisperx.load_align_model(language_code=detected_lang, device=device)
    result = whisperx.align(
        result["segments"], align_model, metadata, audio, device, return_char_alignments=False
    )

    diarize_model = whisperx.DiarizationPipeline(use_auth_token=hf_token, device=device)
    diarize_segments = diarize_model(audio)
    result = whisperx.assign_word_speakers(diarize_segments, result)

    return segments_to_srt(result["segments"])


def process_directory(
    root: Path,
    *,
    model_name: str,
    device: str,
    compute_type: str,
    hf_token: str,
    language: str | None,
    force: bool,
    batch_size: int,
) -> None:
    videos = find_videos(root)
    if not videos:
        logging.warning("No video files found under %s", root)
        return

    logging.info("Loading model '%s' on %s (%s)", model_name, device, compute_type)
    model = whisperx.load_model(model_name, device, compute_type=compute_type)

    failed: list[tuple[Path, str]] = []

    for video_path in videos:
        srt_path = video_path.with_suffix(".srt")

        if srt_path.exists() and not force:
            logging.info("SKIP  %s", video_path)
            continue

        logging.info("START %s", video_path)
        try:
            srt_content = transcribe_video(
                video_path,
                model=model,
                device=device,
                hf_token=hf_token,
                language=language,
                batch_size=batch_size,
            )
            srt_path.write_text(srt_content, encoding="utf-8")
            logging.info("DONE  %s -> %s", video_path.name, srt_path.name)
        except Exception as exc:
            logging.error("FAIL  %s: %s", video_path, exc, exc_info=True)
            failed.append((video_path, str(exc)))

    if failed:
        logging.warning("%d file(s) failed:", len(failed))
        for path, reason in failed:
            logging.warning("  %s: %s", path, reason)
        sys.exit(1)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
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
