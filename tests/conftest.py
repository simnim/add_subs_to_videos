from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_video_dir(tmp_path: Path) -> Path:
    """A temp directory pre-populated with a mix of video and non-video files."""
    (tmp_path / "movie.mp4").touch()
    (tmp_path / "show.mkv").touch()
    (tmp_path / "subtitle.srt").touch()
    (tmp_path / "readme.txt").touch()
    subdir = tmp_path / "sub"
    subdir.mkdir()
    (subdir / "episode.mp4").touch()
    return tmp_path


@pytest.fixture
def mock_whisperx(mocker):
    """
    Patches crawl_srt.whisperx with a MagicMock wired to return canned
    diarized segments. Tests may override individual attributes.
    """
    fake_segments = [
        {"start": 1.0, "end": 3.5, "text": "Hello world", "speaker": "SPEAKER_00"},
        {"start": 4.0, "end": 6.0, "text": "How are you", "speaker": "SPEAKER_01"},
    ]

    mx = mocker.MagicMock()
    mx.load_audio.return_value = b"fake_audio"
    mx.load_model.return_value = mx.model
    mx.model.transcribe.return_value = {"language": "en", "segments": fake_segments}
    mx.load_align_model.return_value = (mx.align_model, mx.metadata)
    mx.align.return_value = {"segments": fake_segments}
    mx.DiarizationPipeline.return_value = mx.diarize_pipeline
    mx.diarize_pipeline.return_value = mx.diarize_segments
    mx.assign_word_speakers.return_value = {"segments": fake_segments}

    mocker.patch("crawl_srt.whisperx", mx)
    return mx
