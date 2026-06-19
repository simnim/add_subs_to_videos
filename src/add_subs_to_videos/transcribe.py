from __future__ import annotations

import contextlib
import io
import logging
import os
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

from .files import find_videos, format_size_mb
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


def default_n_threads() -> int:
    """Best-effort thread count for whisper.cpp: all detected CPU cores."""
    return os.cpu_count() or 4


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
    logging.debug(
        "transcription error env — LD_LIBRARY_PATH=%s PATH=%s SNAP=%s",
        os.environ.get("LD_LIBRARY_PATH", "<unset>"),
        os.environ.get("PATH", "<unset>"),
        os.environ.get("SNAP", "<unset>"),
    )
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


@contextlib.contextmanager
def _capture_native_output(logger_name: str):
    """Routes the wrapped block's OS-level stdout/stderr fds to `logging.debug`.

    whisper.cpp writes diagnostics (backend selection, system info, model load
    details) directly to the C stdout/stderr streams via fprintf, bypassing
    Python's `logging` entirely. Only safe to use around one-shot,
    non-interactive calls such as model loading — never during per-file
    transcription, since it would also swallow tqdm's progress-bar output.
    """
    logger = logging.getLogger(logger_name)
    if not logger.isEnabledFor(logging.DEBUG):
        yield
        return
    try:
        stdout_fd = sys.stdout.fileno()
        stderr_fd = sys.stderr.fileno()
    except (AttributeError, OSError, io.UnsupportedOperation):
        yield
        return

    sys.stdout.flush()
    sys.stderr.flush()
    saved_stdout = os.dup(stdout_fd)
    saved_stderr = os.dup(stderr_fd)
    read_fd, write_fd = os.pipe()
    os.dup2(write_fd, stdout_fd)
    os.dup2(write_fd, stderr_fd)
    os.close(write_fd)

    def _pump() -> None:
        with os.fdopen(read_fd) as reader:
            for line in reader:
                line = line.rstrip()
                if line:
                    logger.debug(line)

    thread = threading.Thread(target=_pump, daemon=True)
    thread.start()
    try:
        yield
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(saved_stdout, stdout_fd)
        os.dup2(saved_stderr, stderr_fd)
        os.close(saved_stdout)
        os.close(saved_stderr)
        thread.join(timeout=1)


def transcribe_video(
    video_path: Path,
    *,
    model: Model,
    language: str | None,
    cancel: threading.Event | None = None,
    on_segment: Callable[[str], None] | None = None,
    on_file_progress: Callable[[float], None] | None = None,
    duration: float | None = None,
    n_threads: int | None = None,
) -> str:
    extra: dict = {}
    if n_threads is not None:
        extra["n_threads"] = n_threads
    if cancel is not None or on_segment is not None or on_file_progress is not None:
        if on_file_progress is not None and duration is None:
            duration = _probe_duration(video_path)
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

    if language is None and logging.getLogger().isEnabledFor(logging.DEBUG):
        try:
            (detected_lang, probability), _ = model.auto_detect_language(str(video_path))
            logging.debug(
                "Detected language for %s: %s (%.0f%%)",
                video_path.name, detected_lang, probability * 100,
            )
        except Exception:
            logging.debug("Language detection failed for %s", video_path.name, exc_info=True)

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
    n_threads: int | None = None,
) -> None:
    videos = find_videos(root)
    if not videos:
        logging.warning("No video files found under %s", root)
        return
    logging.info("Found %d video file(s) under %s", len(videos), root)

    if shutil.which("ffmpeg") is None:
        logging.warning(
            "ffmpeg not found on PATH — transcription of non-WAV files will fail. "
            "Install ffmpeg or ensure it is on PATH."
        )

    logging.debug(
        "startup env — LD_LIBRARY_PATH=%s PATH=%s SNAP=%s",
        os.environ.get("LD_LIBRARY_PATH", "<unset>"),
        os.environ.get("PATH", "<unset>"),
        os.environ.get("SNAP", "<unset>"),
    )
    effective_threads = n_threads if n_threads is not None else default_n_threads()
    max_threads = default_n_threads()
    if effective_threads > max_threads:
        logging.warning(
            "Requested %d thread(s), but only %d core(s) detected — capping",
            effective_threads, max_threads,
        )
        effective_threads = max_threads
    logging.debug("Using %d thread(s) for transcription", effective_threads)

    logging.info("Loading model '%s'", model_name)
    t_load = time.monotonic()
    try:
        with _capture_native_output("whisper.cpp"):
            model = Model(model_name)
    except Exception as exc:
        logging.error("Failed to load model '%s': %s", model_name, exc, exc_info=True)
        sys.exit(1)
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
            size = video_path.stat().st_size
            duration = _probe_duration(video_path)
            duration_str = _format_log_timestamp(duration) if duration is not None else "unknown"
            logging.debug(
                "%s: size=%s duration=%s", video_path.name, format_size_mb(size), duration_str
            )
            t_file = time.monotonic()
            try:
                srt_content = transcribe_video(
                    video_path,
                    model=model,
                    language=language,
                    cancel=cancel,
                    on_segment=on_segment,
                    on_file_progress=_file_progress,
                    duration=duration,
                    n_threads=effective_threads,
                )
                srt_path.write_text(srt_content, encoding="utf-8")
                logging.info(
                    "DONE  %s -> %s (%.1fs)",
                    video_path.name, srt_path.name, time.monotonic() - t_file,
                )
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
