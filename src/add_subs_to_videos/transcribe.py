from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path

from pywhispercpp.model import Model
from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm

from .files import find_videos
from .srt import segments_to_srt


def _raw_to_dicts(raw_segments) -> list[dict]:
    return [
        {"start": seg.t0 / 100.0, "end": seg.t1 / 100.0, "text": seg.text.strip()}
        for seg in raw_segments
    ]


def transcribe_video(
    video_path: Path,
    *,
    model: Model,
    language: str | None,
) -> str:
    raw_segs = model.transcribe(str(video_path), language=language or "")
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
) -> None:
    videos = find_videos(root)
    if not videos:
        logging.warning("No video files found under %s", root)
        return

    logging.info("Loading model '%s'", model_name)
    model = Model(model_name)

    failed: list[tuple[Path, str]] = []
    skipped = transcribed = 0
    t0 = time.monotonic()

    with logging_redirect_tqdm():
        bar = tqdm(
            videos,
            desc="transcribing",
            unit="video",
            disable=not show_progress,
            dynamic_ncols=True,
        )
        for video_path in bar:
            if cancel is not None and cancel.is_set():
                logging.info("Cancelled.")
                break
            bar.set_description(video_path.stem[:40])
            srt_path = video_path.with_suffix(".srt")

            if srt_path.exists() and not force:
                logging.info("SKIP  %s", video_path)
                skipped += 1
                bar.set_postfix(done=transcribed, skip=skipped, fail=len(failed))
                continue

            logging.info("START %s", video_path)
            try:
                srt_content = transcribe_video(
                    video_path,
                    model=model,
                    language=language,
                )
                srt_path.write_text(srt_content, encoding="utf-8")
                logging.info("DONE  %s -> %s", video_path.name, srt_path.name)
                transcribed += 1
            except Exception as exc:
                logging.error("FAIL  %s: %s", video_path, exc, exc_info=True)
                failed.append((video_path, str(exc)))

            bar.set_postfix(done=transcribed, skip=skipped, fail=len(failed))

    elapsed = time.monotonic() - t0
    print(
        f"Summary: {transcribed} transcribed, {skipped} skipped, {len(failed)} failed"
        f"  ({elapsed:.0f}s)"
    )

    if failed:
        logging.warning("%d file(s) failed:", len(failed))
        for path, reason in failed:
            logging.warning("  %s: %s", path, reason)
        sys.exit(1)
