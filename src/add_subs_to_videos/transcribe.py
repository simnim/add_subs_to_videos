from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import torch
from pyannote.audio import Pipeline
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


def assign_speakers(segments: list[dict], diarization) -> list[dict]:
    turns = [
        (turn.start, turn.end, speaker)
        for turn, _, speaker in diarization.itertracks(yield_label=True)
    ]
    for seg in segments:
        best, best_overlap = None, 0.0
        for ts, te, speaker in turns:
            overlap = max(0.0, min(seg["end"], te) - max(seg["start"], ts))
            if overlap > best_overlap:
                best_overlap, best = overlap, speaker
        if best is not None:
            seg["speaker"] = best
    return segments


def transcribe_video(
    video_path: Path,
    *,
    model: Model,
    device: str,
    diarize_pipeline,
    language: str | None,
) -> str:
    raw_segs = model.transcribe(str(video_path), language=language or "")
    segments = _raw_to_dicts(raw_segs)

    if diarize_pipeline is not None:
        diarization = diarize_pipeline(str(video_path))
        segments = assign_speakers(segments, diarization)

    return segments_to_srt(segments)


def process_directory(
    root: Path,
    *,
    model_name: str,
    device: str,
    compute_type: str,
    hf_token: str | None,
    language: str | None,
    force: bool,
    show_progress: bool = True,
) -> None:
    videos = find_videos(root)
    if not videos:
        logging.warning("No video files found under %s", root)
        return

    logging.info("Loading model '%s' on %s (%s)", model_name, device, compute_type)
    model = Model(model_name)

    diarize_pipeline = None
    if hf_token is not None:
        logging.info("Loading diarization pipeline")
        diarize_pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1", use_auth_token=hf_token
        )
        diarize_pipeline.to(torch.device(device))

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
                    device=device,
                    diarize_pipeline=diarize_pipeline,
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
