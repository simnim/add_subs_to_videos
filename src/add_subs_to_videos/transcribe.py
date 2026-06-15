from __future__ import annotations

import logging
import shutil
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
    except FileNotFoundError:
        logging.debug("ffprobe not found; per-file progress will be unavailable")
        return None
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else str(exc)
        logging.debug("ffprobe failed for %s: %s", path, stderr)
        return None
    except ValueError:
        logging.debug("ffprobe returned a non-numeric duration for %s", path)
        return None


def _describe_transcription_error(video_path: Path, exc: Exception) -> str:
    """Returns a human-readable description of a transcription failure.

    pywhispercpp converts non-WAV media via its own `ffmpeg` subprocess call
    with stdout/stderr discarded, so a `CalledProcessError` from it carries no
    detail. Re-run the same conversion ourselves, capturing stderr, to surface
    the actual ffmpeg error (e.g. unsupported codec, corrupt file).
    """
    label = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
    if not isinstance(exc, subprocess.CalledProcessError):
        return label
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-v", "error",
                "-i", str(video_path),
                "-ac", "1", "-ar", "16000",
                "-f", "null", "-",
            ],
            capture_output=True,
            text=True,
        )
    except OSError:
        return label
    stderr_lines = [line for line in result.stderr.splitlines() if line.strip()]
    if stderr_lines:
        logging.debug("ffmpeg diagnostic output for %s:\n%s", video_path, result.stderr.strip())
        return f"ffmpeg: {'; '.join(stderr_lines)}"
    return label


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
        if on_file_progress is not None:
            logging.debug("Probed duration for %s: %s", video_path.name, duration)

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

    if shutil.which("ffmpeg") is None:
        logging.warning(
            "ffmpeg not found on PATH — transcription of non-WAV files will fail. "
            "Install ffmpeg or ensure it is on PATH."
        )

    logging.info("Loading model '%s'", model_name)
    t_load = time.monotonic()
    model = Model(model_name)
    logging.debug("Model '%s' loaded in %.1fs", model_name, time.monotonic() - t_load)

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
            total=total,
            desc="transcribing",
            unit="video",
            disable=not show_progress,
            dynamic_ncols=True,
        )
        file_bar = tqdm(
            total=100,
            desc="file",
            unit="%",
            disable=not show_progress,
            leave=False,
            position=1,
            dynamic_ncols=True,
        )

        current_index = 0

        def _file_progress(fraction: float) -> None:
            file_bar.n = round(fraction * 100, 1)
            file_bar.refresh()
            bar.n = round((current_index - 1) + fraction, 3)
            bar.refresh()
            if on_file_progress is not None:
                on_file_progress(fraction)

        for index, video_path in enumerate(videos, start=1):
            if cancel is not None and cancel.is_set():
                logging.info("Cancelled.")
                break
            current_index = index
            bar.set_description(video_path.stem[:40])
            srt_path = video_path.with_suffix(".srt")
            file_bar.reset()
            _file_progress(0.0)
            _emit("start", index, video_path)

            if srt_path.exists() and not force:
                logging.info("SKIP  %s", video_path)
                skipped += 1
                bar.n = index
                bar.refresh()
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
                    on_file_progress=_file_progress,
                )
                srt_path.write_text(srt_content, encoding="utf-8")
                logging.info("DONE  %s -> %s", video_path.name, srt_path.name)
                _file_progress(1.0)
                transcribed += 1
                bar.set_postfix(done=transcribed, skip=skipped, fail=len(failed))
                _emit("done", index, video_path)
            except _Cancelled:
                logging.info("Cancelled.")
                break
            except Exception as exc:
                reason = _describe_transcription_error(video_path, exc)
                logging.error("FAIL  %s: %s", video_path, reason, exc_info=True)
                failed.append((video_path, reason))
                bar.n = index
                bar.refresh()
                bar.set_postfix(done=transcribed, skip=skipped, fail=len(failed))
                _emit("fail", index, video_path)

        bar.close()
        file_bar.close()

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
