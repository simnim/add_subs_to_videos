from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pywhispercpp.model import Model
from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm

from .files import find_videos
from .srt import segments_to_srt


class _Cancelled(Exception):
    """Raised from a transcription callback to abort mid-file when cancelled."""


@dataclass
class ProgressEvent:
    stage: str  # "start" | "done" | "skip" | "fail" | "summary"
    index: int  # 1-based count of videos processed so far (incl. current)
    total: int
    video: Path | None
    done: int
    skipped: int
    failed: int
    elapsed: float | None = None


def _raw_to_dicts(raw_segments) -> list[dict]:
    return [
        {"start": seg.t0 / 100.0, "end": seg.t1 / 100.0, "text": seg.text.strip()}
        for seg in raw_segments
    ]


def _format_log_timestamp(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes:02d}:{secs:02d}"


def _probe_duration(path: Path) -> float | None:
    """Returns the media duration in seconds via `ffprobe`, or None if unavailable."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "csv=p=0",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return float(result.stdout.strip())
    except (OSError, subprocess.CalledProcessError, ValueError):
        return None


def transcribe_video(
    video_path: Path,
    *,
    model: Model,
    language: str | None,
    cancel: threading.Event | None = None,
    on_segment: Callable[[str], None] | None = None,
    on_file_progress: Callable[[float], None] | None = None,
) -> str:
    extra: dict = {}
    if cancel is not None or on_segment is not None or on_file_progress is not None:
        duration = _probe_duration(video_path) if on_file_progress is not None else None

        def _on_new_segment(segment) -> None:
            if cancel is not None and cancel.is_set():
                raise _Cancelled()
            if on_segment is not None:
                text = segment.text.strip()
                if text:
                    start = _format_log_timestamp(segment.t0 / 100.0)
                    end = _format_log_timestamp(segment.t1 / 100.0)
                    on_segment(f"[{start} --> {end}] {text}")
            if on_file_progress is not None and duration:
                on_file_progress(min(segment.t1 / 100.0 / duration, 1.0))

        extra["new_segment_callback"] = _on_new_segment

    raw_segs = model.transcribe(str(video_path), language=language or "", **extra)
    segments = _raw_to_dicts(raw_segs)
    return segments_to_srt(segments)


def process_directory(
    root: Path,
    *,
    model_name: str,
    language: str | None,
    force: bool,
    show_progress: bool = True,
    cancel: threading.Event | None = None,
    on_progress: Callable[[ProgressEvent], None] | None = None,
    on_segment: Callable[[str], None] | None = None,
    on_file_progress: Callable[[float], None] | None = None,
) -> None:
    videos = find_videos(root)
    if not videos:
        logging.warning("No video files found under %s", root)
        return

    logging.info("Loading model '%s'", model_name)
    model = Model(model_name)

    total = len(videos)
    failed: list[tuple[Path, str]] = []
    skipped = transcribed = 0
    t0 = time.monotonic()

    def _emit(stage: str, index: int, video_path: Path | None, **extra) -> None:
        if on_progress is not None:
            on_progress(
                ProgressEvent(
                    stage=stage,
                    index=index,
                    total=total,
                    video=video_path,
                    done=transcribed,
                    skipped=skipped,
                    failed=len(failed),
                    **extra,
                )
            )

    with logging_redirect_tqdm():
        bar = tqdm(
            videos,
            desc="transcribing",
            unit="video",
            disable=not show_progress,
            dynamic_ncols=True,
        )
        for index, video_path in enumerate(bar, start=1):
            if cancel is not None and cancel.is_set():
                logging.info("Cancelled.")
                break
            bar.set_description(video_path.stem[:40])
            srt_path = video_path.with_suffix(".srt")
            if on_file_progress is not None:
                on_file_progress(0.0)
            _emit("start", index, video_path)

            if srt_path.exists() and not force:
                logging.info("SKIP  %s", video_path)
                skipped += 1
                bar.set_postfix(done=transcribed, skip=skipped, fail=len(failed))
                _emit("skip", index, video_path)
                continue

            logging.info("START %s", video_path)
            try:
                srt_content = transcribe_video(
                    video_path,
                    model=model,
                    language=language,
                    cancel=cancel,
                    on_segment=on_segment,
                    on_file_progress=on_file_progress,
                )
                srt_path.write_text(srt_content, encoding="utf-8")
                logging.info("DONE  %s -> %s", video_path.name, srt_path.name)
                transcribed += 1
                bar.set_postfix(done=transcribed, skip=skipped, fail=len(failed))
                _emit("done", index, video_path)
            except _Cancelled:
                logging.info("Cancelled.")
                break
            except Exception as exc:
                logging.error("FAIL  %s: %s", video_path, exc, exc_info=True)
                failed.append((video_path, str(exc)))
                bar.set_postfix(done=transcribed, skip=skipped, fail=len(failed))
                _emit("fail", index, video_path)

    elapsed = time.monotonic() - t0
    print(
        f"Summary: {transcribed} transcribed, {skipped} skipped, {len(failed)} failed"
        f"  ({elapsed:.0f}s)"
    )
    _emit("summary", total, None, elapsed=elapsed)

    if failed:
        logging.warning("%d file(s) failed:", len(failed))
        for path, reason in failed:
            logging.warning("  %s: %s", path, reason)
        sys.exit(1)
