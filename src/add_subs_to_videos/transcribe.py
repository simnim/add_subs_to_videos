from __future__ import annotations

import logging
import sys
from pathlib import Path

import whisperx

from .files import find_videos
from .srt import segments_to_srt


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
