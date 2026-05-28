from __future__ import annotations

import types
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
def mock_transcribe(mocker):
    """
    Patches add_subs_to_videos.transcribe.Model, Pipeline, and assign_speakers
    with canned outputs. Tests may override individual attributes.
    """
    fake_segments = [
        {"start": 1.0, "end": 3.5, "text": "Hello world", "speaker": "SPEAKER_00"},
        {"start": 4.0, "end": 6.0, "text": "How are you", "speaker": "SPEAKER_01"},
    ]

    def make_seg(start, end, text):
        s = mocker.MagicMock()
        s.t0 = int(start * 100)
        s.t1 = int(end * 100)
        s.text = text
        return s

    raw_segs = [
        make_seg(1.0, 3.5, "Hello world"),
        make_seg(4.0, 6.0, "How are you"),
    ]

    mock_model_instance = mocker.MagicMock()
    mock_model_instance.transcribe.return_value = raw_segs
    mock_model_cls = mocker.patch(
        "add_subs_to_videos.transcribe.Model", return_value=mock_model_instance
    )

    mock_pipeline_instance = mocker.MagicMock()
    mock_pipeline_instance.return_value = mocker.MagicMock()
    mock_pipeline_cls = mocker.MagicMock()
    mock_pipeline_cls.from_pretrained.return_value = mock_pipeline_instance
    mocker.patch("add_subs_to_videos.transcribe.Pipeline", mock_pipeline_cls)

    assign_speakers_mock = mocker.patch(
        "add_subs_to_videos.transcribe.assign_speakers",
        return_value=fake_segments,
    )

    return types.SimpleNamespace(
        model_cls=mock_model_cls,
        model=mock_model_instance,
        pipeline_cls=mock_pipeline_cls,
        pipeline=mock_pipeline_instance,
        assign_speakers_mock=assign_speakers_mock,
        fake_segments=fake_segments,
        raw_segs=raw_segs,
    )
