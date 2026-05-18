"""
Integration test: downloads a real Wikipedia spoken-article audio file and
runs the full crawl_srt pipeline end-to-end (transcription + alignment +
speaker diarization).

Run with:
    uv run pytest tests/test_integration.py -v -s

Skipped automatically if HUGGINGFACE_TOKEN is not set.
The pyannote speaker-diarization model also requires that you have accepted
its license at https://huggingface.co/pyannote/speaker-diarization-3.1.

Audio source: "En-.fun-article.ogg" (~1 min 20 s of clear English speech)
https://commons.wikimedia.org/wiki/File:En-.fun-article.ogg
License: CC BY-SA 4.0
"""

from __future__ import annotations

import os
import urllib.request
from pathlib import Path

import pytest

from crawl_srt import detect_device, process_directory

AUDIO_URL = "https://upload.wikimedia.org/wikipedia/commons/4/48/En-.fun-article.ogg"
# Saved with a .mp4 extension so find_videos() picks it up; ffmpeg probes the
# actual container format and doesn't care about the file extension.
AUDIO_FILENAME = "wikipedia_fun_article.mp4"


@pytest.fixture(scope="module")
def hf_token():
    token = os.environ.get("HUGGINGFACE_TOKEN", "")
    if not token:
        pytest.skip("HUGGINGFACE_TOKEN not set — skipping integration tests")
    return token


@pytest.fixture(scope="module")
def downloaded_audio(tmp_path_factory, hf_token):  # noqa: ARG001
    """Download the Wikipedia audio once per module (skipped if no HF token)."""
    dest = tmp_path_factory.mktemp("audio") / AUDIO_FILENAME
    print(f"\nDownloading {AUDIO_URL} ...")
    # Wikimedia requires a descriptive User-Agent; bare urllib gets a 403.
    req = urllib.request.Request(
        AUDIO_URL,
        headers={"User-Agent": "cc-whisperx-integration-test/1.0 (https://github.com/)"},
    )
    with urllib.request.urlopen(req) as response:
        dest.write_bytes(response.read())
    assert dest.stat().st_size > 0, "Downloaded file is empty"
    return dest


@pytest.mark.integration
def test_srt_file_is_created(downloaded_audio, hf_token):
    """process_directory writes a .srt sidecar next to the video file."""
    video_dir = downloaded_audio.parent
    srt_path = downloaded_audio.with_suffix(".srt")
    srt_path.unlink(missing_ok=True)  # ensure clean state

    device, compute_type = detect_device()
    process_directory(
        video_dir,
        model_name="tiny",
        device=device,
        compute_type=compute_type,
        hf_token=hf_token,
        language="en",
        force=True,
        batch_size=16,
    )

    assert srt_path.exists(), ".srt file was not created"


@pytest.mark.integration
def test_srt_content_is_valid(downloaded_audio, hf_token):
    """The generated .srt contains well-formed cues."""
    srt_path = downloaded_audio.with_suffix(".srt")
    # Re-use the file written by the previous test (module-scoped audio fixture
    # means both tests share the same tmp dir; run order is top-to-bottom).
    if not srt_path.exists():
        device, compute_type = detect_device()
        process_directory(
            downloaded_audio.parent,
            model_name="tiny",
            device=device,
            compute_type=compute_type,
            hf_token=hf_token,
            language="en",
            force=True,
            batch_size=16,
        )

    content = srt_path.read_text(encoding="utf-8")

    # Must have at least one cue
    assert content.strip(), ".srt file is empty"

    # Every cue block must contain a --> timestamp line
    assert " --> " in content

    # Timestamps must use comma as millisecond separator (SRT spec)
    import re
    timestamp_lines = re.findall(r"\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}", content)
    assert len(timestamp_lines) > 0, "No valid SRT timestamp lines found"


@pytest.mark.integration
def test_srt_contains_speaker_labels(downloaded_audio, hf_token):
    """Diarization labels (SPEAKER_XX) appear in the cue text."""
    srt_path = downloaded_audio.with_suffix(".srt")
    if not srt_path.exists():
        device, compute_type = detect_device()
        process_directory(
            downloaded_audio.parent,
            model_name="tiny",
            device=device,
            compute_type=compute_type,
            hf_token=hf_token,
            language="en",
            force=True,
            batch_size=16,
        )

    content = srt_path.read_text(encoding="utf-8")
    assert "SPEAKER_" in content, "No speaker labels found in .srt output"


@pytest.mark.integration
def test_skip_logic_honours_existing_srt(downloaded_audio, hf_token, mocker):
    """process_directory skips a file that already has a .srt (no --force)."""
    srt_path = downloaded_audio.with_suffix(".srt")
    srt_path.write_text("sentinel content", encoding="utf-8")

    load_audio_spy = mocker.patch("crawl_srt.whisperx.load_audio", wraps=None)
    # wraps=None means the mock returns MagicMock but we just want call count

    device, compute_type = detect_device()
    process_directory(
        downloaded_audio.parent,
        model_name="tiny",
        device=device,
        compute_type=compute_type,
        hf_token=hf_token,
        language="en",
        force=False,   # do NOT force
        batch_size=16,
    )

    load_audio_spy.assert_not_called()
    # Original content must be preserved
    assert srt_path.read_text(encoding="utf-8") == "sentinel content"
