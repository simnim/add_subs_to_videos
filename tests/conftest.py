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
    """Patches add_subs_to_videos.transcribe.Model with canned outputs."""

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

    return types.SimpleNamespace(
        model_cls=mock_model_cls,
        model=mock_model_instance,
        raw_segs=raw_segs,
    )
