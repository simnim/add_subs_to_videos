"""
Integration test: runs the full add_subs_to_videos pipeline end-to-end
(transcription only) against a bundled Wikipedia spoken-article audio file.

Run with:
    uv run pytest tests/test_integration.py -v -s

Audio source: "En-.fun-article.ogg" (~1 min 20 s of clear English speech)
https://commons.wikimedia.org/wiki/File:En-.fun-article.ogg
License: CC BY-SA 4.0
"""

from __future__ import annotations

import re
import shutil
import threading
import time
from pathlib import Path

import pytest

from add_subs_to_videos.transcribe import process_directory

AUDIO_SOURCE = Path(__file__).parent / "demo-audio" / "wiki-example-audio.ogg"
# Saved with a .mp4 extension so find_videos() picks it up; ffmpeg probes the
# actual container format and doesn't care about the file extension.
AUDIO_FILENAME = "wikipedia_fun_article.mp4"


@pytest.fixture(scope="module")
def downloaded_audio(tmp_path_factory):
    """Copy the bundled Wikipedia audio into a temp dir once per module."""
    dest = tmp_path_factory.mktemp("audio") / AUDIO_FILENAME
    shutil.copyfile(AUDIO_SOURCE, dest)
    assert dest.stat().st_size > 0, "Copied file is empty"
    return dest


@pytest.mark.integration
def test_srt_file_is_created(downloaded_audio):
    """process_directory writes a .srt sidecar next to the video file."""
    video_dir = downloaded_audio.parent
    srt_path = downloaded_audio.with_suffix(".srt")
    srt_path.unlink(missing_ok=True)

    process_directory(video_dir, model_name="tiny", language="en", force=True, n_threads=1)

    assert srt_path.exists(), ".srt file was not created"


@pytest.mark.integration
def test_srt_content_is_valid(downloaded_audio):
    """The generated .srt contains well-formed cues."""
    srt_path = downloaded_audio.with_suffix(".srt")
    if not srt_path.exists():
        process_directory(
            downloaded_audio.parent, model_name="tiny", language="en", force=True, n_threads=1
        )

    content = srt_path.read_text(encoding="utf-8")

    assert content.strip(), ".srt file is empty"
    assert " --> " in content

    timestamp_lines = re.findall(
        r"\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}", content
    )
    assert len(timestamp_lines) > 0, "No valid SRT timestamp lines found"


@pytest.mark.integration
def test_skip_logic_honours_existing_srt(downloaded_audio):
    """process_directory skips a file that already has a .srt (no --force)."""
    srt_path = downloaded_audio.with_suffix(".srt")
    srt_path.write_text("sentinel content", encoding="utf-8")

    process_directory(
        downloaded_audio.parent, model_name="tiny", language="en", force=False, n_threads=1
    )

    assert srt_path.read_text(encoding="utf-8") == "sentinel content"


@pytest.mark.integration
def test_cancel_mid_transcription_preserves_partial_part_file(downloaded_audio):
    """Cancelling a real, in-progress transcription leaves partial content in
    .srt.part (flushed by whisper.cpp's native segment callback) and never
    writes the final .srt."""
    srt_path = downloaded_audio.with_suffix(".srt")
    part_path = srt_path.with_name(srt_path.name + ".part")
    srt_path.unlink(missing_ok=True)
    part_path.unlink(missing_ok=True)

    cancel = threading.Event()
    thread = threading.Thread(
        target=process_directory,
        args=(downloaded_audio.parent,),
        kwargs=dict(
            model_name="tiny",
            language="en",
            force=True,
            n_threads=1,
            cancel=cancel,
            show_progress=False,
        ),
    )
    thread.start()

    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if part_path.exists() and " --> " in part_path.read_text(encoding="utf-8"):
                break
            time.sleep(0.05)
        else:
            pytest.fail("Timed out waiting for partial .srt.part content to appear")

        cancel.set()
        thread.join(timeout=30)
        assert not thread.is_alive(), "process_directory did not stop after cancellation"

        assert part_path.exists(), ".srt.part should be retained after cancellation"
        partial_content = part_path.read_text(encoding="utf-8")
        assert " --> " in partial_content
        assert not srt_path.exists(), "final .srt should not be written after cancellation"
    finally:
        thread.join(timeout=5)
        part_path.unlink(missing_ok=True)
