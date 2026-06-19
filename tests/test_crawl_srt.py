from __future__ import annotations

import re
from pathlib import Path

import pytest

from add_subs_to_videos.cli import build_parser
from add_subs_to_videos.files import VIDEO_EXTENSIONS, build_video_tree, find_videos, format_size_mb
from add_subs_to_videos.srt import format_srt_timestamp, segments_to_srt
from add_subs_to_videos.transcribe import (
    _Cancelled,
    _capture_native_output,
    _describe_transcription_error,
    _download_model,
    _format_log_timestamp,
    _probe_duration,
    _raw_to_dicts,
    default_n_threads,
    is_model_downloaded,
    model_file_path,
    process_directory,
    transcribe_video,
)


# ---------------------------------------------------------------------------
# format_srt_timestamp
# ---------------------------------------------------------------------------


class TestFormatSrtTimestamp:
    def test_zero(self):
        assert format_srt_timestamp(0.0) == "00:00:00,000"

    def test_simple_seconds(self):
        assert format_srt_timestamp(1.5) == "00:00:01,500"

    def test_minute_rollover(self):
        assert format_srt_timestamp(61.0) == "00:01:01,000"

    def test_hour_rollover(self):
        assert format_srt_timestamp(3723.456) == "01:02:03,456"

    def test_rounding_up(self):
        # 1.9999 * 1000 = 1999.9 → rounds to 2000ms → 00:00:02,000
        assert format_srt_timestamp(1.9999) == "00:00:02,000"

    def test_exactly_one_hour(self):
        assert format_srt_timestamp(3600.0) == "01:00:00,000"

    def test_millisecond_precision(self):
        assert format_srt_timestamp(0.123) == "00:00:00,123"

    def test_near_minute_boundary(self):
        assert format_srt_timestamp(59.999) == "00:00:59,999"

    def test_over_99_hours_not_truncated(self):
        # 100 hours, no wraparound or digit truncation in the hour field
        assert format_srt_timestamp(360000.0) == "100:00:00,000"

    def test_negative_seconds_current_behavior(self):
        # Not a supported input (segments are never negative in practice), but
        # pinned down so a future change to this is a deliberate decision.
        assert format_srt_timestamp(-1.5) == "-1:59:58,500"


class TestFormatLogTimestamp:
    def test_zero(self):
        assert _format_log_timestamp(0.0) == "00:00"

    def test_seconds_only(self):
        assert _format_log_timestamp(45.0) == "00:45"

    def test_minute_rollover(self):
        assert _format_log_timestamp(65.0) == "01:05"

    def test_truncates_fractional_seconds(self):
        assert _format_log_timestamp(59.9) == "00:59"

    def test_hour_plus_renders_as_minutes(self):
        assert _format_log_timestamp(3661.0) == "61:01"


# ---------------------------------------------------------------------------
# segments_to_srt
# ---------------------------------------------------------------------------


class TestSegmentsToSrt:
    def test_empty_list(self):
        assert segments_to_srt([]) == ""

    def test_whitespace_only_text_is_skipped(self):
        segs = [{"start": 0.0, "end": 1.0, "text": "   "}]
        assert segments_to_srt(segs) == ""

    def test_single_segment(self):
        segs = [{"start": 1.0, "end": 3.5, "text": "Hello world"}]
        result = segments_to_srt(segs)
        assert result == (
            "1\n"
            "00:00:01,000 --> 00:00:03,500\n"
            "Hello world\n"
        )

    def test_multiple_segments_sequential_index(self):
        segs = [
            {"start": 0.0, "end": 1.0, "text": "First"},
            {"start": 1.5, "end": 2.5, "text": "Second"},
        ]
        result = segments_to_srt(segs)
        lines = result.split("\n")
        assert lines[0] == "1"
        assert lines[4] == "2"

    def test_blank_line_between_cues(self):
        segs = [
            {"start": 0.0, "end": 1.0, "text": "First"},
            {"start": 1.5, "end": 2.5, "text": "Second"},
        ]
        result = segments_to_srt(segs)
        assert "\n\n" in result

    def test_empty_segments_do_not_consume_index(self):
        segs = [
            {"start": 0.0, "end": 1.0, "text": "  "},
            {"start": 1.5, "end": 2.5, "text": "Second"},
        ]
        result = segments_to_srt(segs)
        assert result.startswith("1\n")
        assert "2\n" not in result

    def test_text_is_stripped(self):
        segs = [{"start": 0.0, "end": 1.0, "text": "  padded  "}]
        result = segments_to_srt(segs)
        assert "padded" in result
        assert "  padded  " not in result

    def test_comma_used_as_ms_separator(self):
        segs = [{"start": 1.5, "end": 2.5, "text": "Check"}]
        result = segments_to_srt(segs)
        assert "," in result
        timestamp_line = result.split("\n")[1]
        assert "." not in timestamp_line

    def test_missing_key_raises_key_error(self):
        segs = [{"start": 0.0, "end": 1.0}]
        with pytest.raises(KeyError):
            segments_to_srt(segs)

    def test_multiline_text_preserved(self):
        segs = [{"start": 0.0, "end": 1.0, "text": "  Line one\nLine two  "}]
        result = segments_to_srt(segs)
        assert "Line one\nLine two" in result
        assert "  Line one" not in result
        assert "Line two  " not in result


# ---------------------------------------------------------------------------
# build_parser
# ---------------------------------------------------------------------------


class TestBuildParser:
    def test_missing_model_defaults_to_medium(self):
        parser = build_parser()
        args = parser.parse_args(["/some/dir"])
        assert args.model == "medium"

    def test_invalid_model_exits(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["/some/dir", "--model", "xlarge"])

    def test_valid_model_accepted(self):
        parser = build_parser()
        args = parser.parse_args(["/some/dir", "--model", "large-v3"])
        assert args.model == "large-v3"

    def test_directory_parsed_as_path(self):
        parser = build_parser()
        args = parser.parse_args(["/some/dir", "--model", "small"])
        assert isinstance(args.directory, Path)

    def test_force_defaults_false(self):
        parser = build_parser()
        args = parser.parse_args(["/some/dir", "--model", "small"])
        assert args.force is False

    def test_force_flag_sets_true(self):
        parser = build_parser()
        args = parser.parse_args(["/some/dir", "--model", "small", "--force"])
        assert args.force is True

    def test_language_defaults_to_none(self):
        parser = build_parser()
        args = parser.parse_args(["/some/dir", "--model", "small"])
        assert args.language is None

    def test_language_set(self):
        parser = build_parser()
        args = parser.parse_args(["/some/dir", "--model", "small", "--language", "en"])
        assert args.language == "en"

    def test_quiet_flag(self):
        parser = build_parser()
        args = parser.parse_args(["/some/dir", "--model", "small", "--quiet"])
        assert args.quiet is True
        assert args.verbose is False

    def test_verbose_flag(self):
        parser = build_parser()
        args = parser.parse_args(["/some/dir", "--model", "small", "--verbose"])
        assert args.verbose is True
        assert args.quiet is False

    def test_quiet_short_flag(self):
        parser = build_parser()
        args = parser.parse_args(["/some/dir", "-q"])
        assert args.quiet is True
        assert args.verbose is False

    def test_verbose_short_flag(self):
        parser = build_parser()
        args = parser.parse_args(["/some/dir", "-v"])
        assert args.verbose is True
        assert args.quiet is False

    def test_quiet_and_verbose_are_mutually_exclusive(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["/some/dir", "--model", "small", "--quiet", "--verbose"])

    def test_directory_is_optional(self):
        # nargs="?" — omitting directory gives None, not an error from argparse
        parser = build_parser()
        args = parser.parse_args([])
        assert args.directory is None

    def test_config_model_overrides_hardcoded_default(self):
        parser = build_parser()
        parser.set_defaults(model="large-v3")
        args = parser.parse_args(["/some/dir"])
        assert args.model == "large-v3"

    def test_cli_model_beats_config_default(self):
        parser = build_parser()
        parser.set_defaults(model="large-v3")
        args = parser.parse_args(["/some/dir", "--model", "tiny"])
        assert args.model == "tiny"

    def test_config_language_overrides_none_default(self):
        parser = build_parser()
        parser.set_defaults(language="ja")
        args = parser.parse_args(["/some/dir"])
        assert args.language == "ja"

    def test_cli_language_beats_config_default(self):
        parser = build_parser()
        parser.set_defaults(language="ja")
        args = parser.parse_args(["/some/dir", "--language", "en"])
        assert args.language == "en"


# ---------------------------------------------------------------------------
# find_videos
# ---------------------------------------------------------------------------


class TestFindVideos:
    def test_returns_only_video_files(self, tmp_video_dir):
        videos = find_videos(tmp_video_dir)
        suffixes = {p.suffix for p in videos}
        assert suffixes <= VIDEO_EXTENSIONS

    def test_excludes_non_video_files(self, tmp_video_dir):
        videos = find_videos(tmp_video_dir)
        names = {p.name for p in videos}
        assert "subtitle.srt" not in names
        assert "readme.txt" not in names

    def test_recursive_search(self, tmp_video_dir):
        videos = find_videos(tmp_video_dir)
        names = {p.name for p in videos}
        assert "episode.mp4" in names

    def test_result_is_sorted(self, tmp_video_dir):
        videos = find_videos(tmp_video_dir)
        assert videos == sorted(videos)

    def test_empty_directory_returns_empty_list(self, tmp_path):
        assert find_videos(tmp_path) == []

    def test_single_video_file_returns_list_with_that_file(self, tmp_path):
        f = tmp_path / "file.mp4"
        f.touch()
        assert find_videos(f) == [f]

    def test_non_video_file_exits(self, tmp_path):
        f = tmp_path / "notes.txt"
        f.touch()
        with pytest.raises(SystemExit):
            find_videos(f)

    def test_nonexistent_path_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            find_videos(tmp_path / "missing")

    def test_deeply_nested_files_found(self, tmp_path):
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        (deep / "deep.mp4").touch()
        assert any(p.name == "deep.mp4" for p in find_videos(tmp_path))

    def test_hidden_directory_contents_found(self, tmp_path):
        hidden = tmp_path / ".hidden"
        hidden.mkdir()
        (hidden / "video.mp4").touch()
        assert any(p.name == "video.mp4" for p in find_videos(tmp_path))

    def test_case_insensitive_extensions(self, tmp_path):
        (tmp_path / "VIDEO.MP4").touch()
        (tmp_path / "clip.MKV").touch()
        videos = find_videos(tmp_path)
        assert len(videos) == 2

    def test_all_supported_extensions_found(self, tmp_path):
        for ext in VIDEO_EXTENSIONS:
            (tmp_path / f"file{ext}").touch()
        videos = find_videos(tmp_path)
        assert len(videos) == len(VIDEO_EXTENSIONS)

    def test_symlinked_subdirectory_is_not_traversed(self, tmp_path):
        # pathlib's rglob does not descend into symlinked directories by
        # default (Python 3.13+); pin this down since it affects discovery.
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        (real_dir / "linked.mp4").touch()
        root = tmp_path / "root"
        root.mkdir()
        try:
            (root / "link").symlink_to(real_dir, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not supported on this platform")
        assert not any(p.name == "linked.mp4" for p in find_videos(root))


# ---------------------------------------------------------------------------
# format_size_mb
# ---------------------------------------------------------------------------


class TestFormatSizeMb:
    def test_zero_bytes(self):
        assert format_size_mb(0) == "0.0M"

    def test_under_ten_mb_uses_one_decimal(self):
        assert format_size_mb(int(5.4 * 1024 * 1024)) == "5.4M"

    def test_at_ten_mb_uses_no_decimal(self):
        assert format_size_mb(10 * 1024 * 1024) == "10M"

    def test_just_under_ten_mb_uses_one_decimal(self):
        assert format_size_mb(10 * 1024 * 1024 - 1) == "10.0M"

    def test_large_value(self):
        assert format_size_mb(19 * 1024 * 1024) == "19M"


# ---------------------------------------------------------------------------
# build_video_tree
# ---------------------------------------------------------------------------


class TestBuildVideoTree:
    def test_single_video_file(self, tmp_path):
        f = tmp_path / "clip.mp4"
        f.write_bytes(b"x" * (2 * 1024 * 1024))
        assert build_video_tree(f) == f"[{format_size_mb(f.stat().st_size):>4}]  clip.mp4"

    def test_empty_directory_returns_empty_string(self, tmp_path):
        assert build_video_tree(tmp_path) == ""

    def test_directory_with_only_non_video_files_returns_empty_string(self, tmp_path):
        (tmp_path / "readme.txt").touch()
        assert build_video_tree(tmp_path) == ""

    def test_flat_directory(self, tmp_path):
        (tmp_path / "a.mp4").write_bytes(b"x" * 1024 * 1024)
        (tmp_path / "b.mkv").write_bytes(b"x" * 1024 * 1024)
        (tmp_path / "notes.txt").touch()
        tree = build_video_tree(tmp_path)
        lines = tree.splitlines()
        assert len(lines) == 3
        assert lines[0] == f"[{format_size_mb(2 * 1024 * 1024):>4}]  {tmp_path.name}/"
        assert lines[1].startswith("├── ") and "a.mp4" in lines[1]
        assert lines[2].startswith("└── ") and "b.mkv" in lines[2]
        assert "notes.txt" not in tree

    def test_nested_directory_sums_and_prefixes(self, tmp_path):
        (tmp_path / "a.mp4").write_bytes(b"x" * 1024 * 1024)
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "b.mp4").write_bytes(b"x" * 2 * 1024 * 1024)
        tree = build_video_tree(tmp_path)
        lines = tree.splitlines()
        assert lines[0] == f"[{format_size_mb(3 * 1024 * 1024):>4}]  {tmp_path.name}/"
        assert lines[1].startswith("├── ") and "a.mp4" in lines[1]
        assert lines[2].startswith("└── ") and "sub/" in lines[2]
        assert f"[{format_size_mb(2 * 1024 * 1024):>4}]" in lines[2]
        assert lines[3] == f"    └── [{format_size_mb(2 * 1024 * 1024):>4}]  b.mp4"

    def test_video_free_subdirectory_is_pruned(self, tmp_path):
        (tmp_path / "a.mp4").touch()
        empty_sub = tmp_path / "empty"
        empty_sub.mkdir()
        (empty_sub / "notes.txt").touch()
        tree = build_video_tree(tmp_path)
        assert "empty" not in tree

    def test_ordering_interleaves_dirs_and_files(self, tmp_path):
        (tmp_path / "z.mp4").touch()
        sub = tmp_path / "m"
        sub.mkdir()
        (sub / "n.mp4").touch()
        (tmp_path / "a.mp4").touch()
        tree = build_video_tree(tmp_path)
        lines = tree.splitlines()
        top_level = [line for line in lines[1:] if line.startswith(("├── ", "└── "))]
        names = [line.split("  ", 1)[1] for line in top_level]
        assert names == ["a.mp4", "m/", "z.mp4"]


# ---------------------------------------------------------------------------
# _raw_to_dicts
# ---------------------------------------------------------------------------


class TestRawToDicts:
    def _make_seg(self, mocker, t0, t1, text):
        seg = mocker.MagicMock()
        seg.t0 = t0
        seg.t1 = t1
        seg.text = text
        return seg

    def test_centiseconds_converted_to_seconds(self, mocker):
        seg = self._make_seg(mocker, t0=100, t1=350, text="hi")
        result = _raw_to_dicts([seg])
        assert result[0]["start"] == pytest.approx(1.0)
        assert result[0]["end"] == pytest.approx(3.5)

    def test_text_stripped(self, mocker):
        seg = self._make_seg(mocker, t0=0, t1=100, text="  hello  ")
        result = _raw_to_dicts([seg])
        assert result[0]["text"] == "hello"

    def test_multiple_segments_preserved(self, mocker):
        segs = [
            self._make_seg(mocker, 0, 100, "first"),
            self._make_seg(mocker, 200, 300, "second"),
        ]
        result = _raw_to_dicts(segs)
        assert len(result) == 2
        assert result[1]["start"] == pytest.approx(2.0)

    def test_zero_timestamps(self, mocker):
        seg = self._make_seg(mocker, t0=0, t1=0, text="x")
        result = _raw_to_dicts([seg])
        assert result[0]["start"] == 0.0
        assert result[0]["end"] == 0.0

    def test_empty_input(self):
        assert _raw_to_dicts([]) == []

    def test_internal_whitespace_preserved(self, mocker):
        seg = self._make_seg(mocker, 0, 100, "  hello  world  ")
        result = _raw_to_dicts([seg])
        assert result[0]["text"] == "hello  world"


# ---------------------------------------------------------------------------
# _probe_duration
# ---------------------------------------------------------------------------


class TestProbeDuration:
    def test_returns_duration_from_ffprobe_stdout(self, tmp_path, mocker):
        result = mocker.MagicMock(stdout="12.5\n")
        mocker.patch("add_subs_to_videos.transcribe.subprocess.run", return_value=result)
        assert _probe_duration(tmp_path / "clip.mp4") == 12.5

    def test_returns_none_and_logs_when_ffprobe_missing(self, tmp_path, mocker, caplog):
        mocker.patch(
            "add_subs_to_videos.transcribe.subprocess.run", side_effect=FileNotFoundError
        )
        with caplog.at_level("DEBUG", logger="root"):
            assert _probe_duration(tmp_path / "clip.mp4") is None
        assert "ffprobe not found" in caplog.text

    def test_returns_none_and_logs_when_ffprobe_fails(self, tmp_path, mocker, caplog):
        import subprocess

        mocker.patch(
            "add_subs_to_videos.transcribe.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "ffprobe", stderr="boom"),
        )
        with caplog.at_level("DEBUG", logger="root"):
            assert _probe_duration(tmp_path / "clip.mp4") is None
        assert "boom" in caplog.text

    def test_returns_none_and_logs_when_ffprobe_fails_without_stderr(self, tmp_path, mocker, caplog):
        import subprocess

        mocker.patch(
            "add_subs_to_videos.transcribe.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "ffprobe"),
        )
        with caplog.at_level("DEBUG", logger="root"):
            assert _probe_duration(tmp_path / "clip.mp4") is None
        assert "ffprobe failed" in caplog.text

    def test_returns_none_and_logs_when_output_is_not_a_number(self, tmp_path, mocker, caplog):
        result = mocker.MagicMock(stdout="N/A\n")
        mocker.patch("add_subs_to_videos.transcribe.subprocess.run", return_value=result)
        with caplog.at_level("DEBUG", logger="root"):
            assert _probe_duration(tmp_path / "clip.mp4") is None
        assert "non-numeric duration" in caplog.text


# ---------------------------------------------------------------------------
# _describe_transcription_error
# ---------------------------------------------------------------------------


class TestDescribeTranscriptionError:
    def test_non_called_process_error_passthrough(self, tmp_path):
        exc = RuntimeError("boom")
        assert _describe_transcription_error(tmp_path / "clip.mp4", exc) == "RuntimeError: boom"

    def test_exception_with_empty_message_uses_type_name_only(self, tmp_path):
        exc = RuntimeError()
        assert _describe_transcription_error(tmp_path / "clip.mp4", exc) == "RuntimeError"

    def test_called_process_error_uses_ffmpeg_stderr(self, tmp_path, mocker):
        import subprocess

        exc = subprocess.CalledProcessError(1, "ffmpeg")
        result = mocker.MagicMock(
            stderr="Some warning\nInvalid data found when processing input\n"
        )
        mocker.patch("add_subs_to_videos.transcribe.subprocess.run", return_value=result)
        msg = _describe_transcription_error(tmp_path / "clip.mp4", exc)
        assert msg == "ffmpeg: Some warning; Invalid data found when processing input"

    def test_called_process_error_falls_back_when_no_stderr(self, tmp_path, mocker):
        import subprocess

        exc = subprocess.CalledProcessError(1, "ffmpeg")
        result = mocker.MagicMock(stderr="")
        mocker.patch("add_subs_to_videos.transcribe.subprocess.run", return_value=result)
        assert _describe_transcription_error(tmp_path / "clip.mp4", exc) == f"CalledProcessError: {exc}"

    def test_called_process_error_falls_back_when_ffmpeg_missing(self, tmp_path, mocker):
        import subprocess

        exc = subprocess.CalledProcessError(1, "ffmpeg")
        mocker.patch(
            "add_subs_to_videos.transcribe.subprocess.run", side_effect=FileNotFoundError
        )
        assert _describe_transcription_error(tmp_path / "clip.mp4", exc) == f"CalledProcessError: {exc}"


# ---------------------------------------------------------------------------
# _capture_native_output
# ---------------------------------------------------------------------------


class TestCaptureNativeOutput:
    def test_noop_when_not_at_debug_level(self, caplog, capfd):
        import os

        with caplog.at_level("INFO", logger="root"):
            with _capture_native_output("whisper.cpp"):
                os.write(1, b"stdout line\n")

        assert "stdout line" not in caplog.text
        assert "stdout line" in capfd.readouterr().out

    def test_restores_stdout_and_stderr_fds_after_use(self, caplog, capfd):
        import os

        with caplog.at_level("DEBUG", logger="root"):
            with _capture_native_output("whisper.cpp"):
                pass
            os.write(1, b"after capture\n")

        assert "after capture" in capfd.readouterr().out

    def test_restores_fds_when_body_raises(self, caplog, capfd):
        import os

        with caplog.at_level("DEBUG", logger="root"):
            with pytest.raises(ValueError):
                with _capture_native_output("whisper.cpp"):
                    raise ValueError("boom")
            os.write(1, b"after raise\n")

        assert "after raise" in capfd.readouterr().out

    def test_falls_back_when_stdout_has_no_fileno(self, caplog, monkeypatch):
        import io

        class _NoFileno(io.StringIO):
            def fileno(self):
                raise io.UnsupportedOperation("fileno")

        monkeypatch.setattr("sys.stdout", _NoFileno())
        ran = False
        with caplog.at_level("DEBUG", logger="root"):
            with _capture_native_output("whisper.cpp"):
                ran = True

        assert ran


# ---------------------------------------------------------------------------
# transcribe_video
# ---------------------------------------------------------------------------


class TestTranscribeVideo:
    def test_returns_srt_string(self, tmp_path, mock_transcribe):
        video = tmp_path / "clip.mp4"
        video.touch()
        result = transcribe_video(video, model=mock_transcribe.model, language=None)
        assert isinstance(result, str)
        assert "-->" in result

    def test_pipeline_call_order(self, tmp_path, mock_transcribe):
        video = tmp_path / "clip.mp4"
        video.touch()
        transcribe_video(video, model=mock_transcribe.model, language=None)
        mock_transcribe.model.transcribe.assert_called_once_with(str(video), language="")

    def test_language_passed_to_transcribe(self, tmp_path, mock_transcribe):
        video = tmp_path / "clip.mp4"
        video.touch()
        transcribe_video(video, model=mock_transcribe.model, language="fr")
        mock_transcribe.model.transcribe.assert_called_once_with(str(video), language="fr")

    def test_language_none_passed_as_empty_string(self, tmp_path, mock_transcribe):
        video = tmp_path / "clip.mp4"
        video.touch()
        transcribe_video(video, model=mock_transcribe.model, language=None)
        mock_transcribe.model.transcribe.assert_called_once_with(str(video), language="")

    def test_propagates_model_exception(self, tmp_path, mock_transcribe):
        mock_transcribe.model.transcribe.side_effect = RuntimeError("GPU OOM")
        video = tmp_path / "clip.mp4"
        video.touch()
        with pytest.raises(RuntimeError, match="GPU OOM"):
            transcribe_video(video, model=mock_transcribe.model, language=None)

    def test_logs_detected_language_when_auto_and_verbose(self, tmp_path, mock_transcribe, caplog):
        import numpy as np

        video = tmp_path / "clip.mp4"
        video.touch()
        mock_transcribe.model.auto_detect_language.return_value = (("en", np.float32(0.97)), {})

        with caplog.at_level("DEBUG", logger="root"):
            transcribe_video(video, model=mock_transcribe.model, language=None)

        assert "Detected language for clip.mp4: en (97%)" in caplog.text

    def test_skips_language_detection_when_language_pinned(self, tmp_path, mock_transcribe, caplog):
        video = tmp_path / "clip.mp4"
        video.touch()

        with caplog.at_level("DEBUG", logger="root"):
            transcribe_video(video, model=mock_transcribe.model, language="en")

        mock_transcribe.model.auto_detect_language.assert_not_called()

    def test_skips_language_detection_when_not_verbose(self, tmp_path, mock_transcribe):
        video = tmp_path / "clip.mp4"
        video.touch()
        transcribe_video(video, model=mock_transcribe.model, language=None)
        mock_transcribe.model.auto_detect_language.assert_not_called()

    def test_language_detection_failure_is_logged_and_does_not_raise(self, tmp_path, mock_transcribe, caplog):
        video = tmp_path / "clip.mp4"
        video.touch()
        mock_transcribe.model.auto_detect_language.side_effect = RuntimeError("decode failed")

        with caplog.at_level("DEBUG", logger="root"):
            result = transcribe_video(video, model=mock_transcribe.model, language=None)

        assert "Language detection failed for clip.mp4" in caplog.text
        assert "-->" in result

    def test_no_callback_passed_when_cancel_is_none(self, tmp_path, mock_transcribe):
        video = tmp_path / "clip.mp4"
        video.touch()
        transcribe_video(video, model=mock_transcribe.model, language=None, cancel=None)
        mock_transcribe.model.transcribe.assert_called_once_with(str(video), language="")

    def test_cancel_set_mid_transcription_raises_cancelled(self, tmp_path, mock_transcribe):
        import threading

        cancel = threading.Event()

        def fake_transcribe(media, language="", new_segment_callback=None):
            new_segment_callback(mock_transcribe.raw_segs[0])
            cancel.set()
            new_segment_callback(mock_transcribe.raw_segs[1])
            return mock_transcribe.raw_segs

        mock_transcribe.model.transcribe.side_effect = fake_transcribe
        video = tmp_path / "clip.mp4"
        video.touch()

        with pytest.raises(_Cancelled):
            transcribe_video(video, model=mock_transcribe.model, language=None, cancel=cancel)

    def test_cancel_not_yet_set_completes_normally(self, tmp_path, mock_transcribe):
        import threading

        cancel = threading.Event()

        def fake_transcribe(media, language="", new_segment_callback=None):
            new_segment_callback(mock_transcribe.raw_segs[0])
            return mock_transcribe.raw_segs

        mock_transcribe.model.transcribe.side_effect = fake_transcribe
        video = tmp_path / "clip.mp4"
        video.touch()

        result = transcribe_video(video, model=mock_transcribe.model, language=None, cancel=cancel)
        assert "-->" in result

    def test_no_callback_passed_when_on_segment_is_none(self, tmp_path, mock_transcribe):
        video = tmp_path / "clip.mp4"
        video.touch()
        transcribe_video(video, model=mock_transcribe.model, language=None, on_segment=None)
        mock_transcribe.model.transcribe.assert_called_once_with(str(video), language="")

    def test_on_segment_receives_formatted_lines(self, tmp_path, mock_transcribe):
        def fake_transcribe(media, language="", new_segment_callback=None):
            for seg in mock_transcribe.raw_segs:
                new_segment_callback(seg)
            return mock_transcribe.raw_segs

        mock_transcribe.model.transcribe.side_effect = fake_transcribe
        video = tmp_path / "clip.mp4"
        video.touch()

        lines: list[str] = []
        transcribe_video(
            video, model=mock_transcribe.model, language=None, on_segment=lines.append
        )
        assert lines == [
            "[00:01 --> 00:03] Hello world",
            "[00:04 --> 00:06] How are you",
        ]

    def test_on_segment_skips_blank_text(self, tmp_path, mock_transcribe):
        def fake_transcribe(media, language="", new_segment_callback=None):
            blank = mock_transcribe.raw_segs[0]
            blank.text = "   "
            new_segment_callback(blank)
            return mock_transcribe.raw_segs

        mock_transcribe.model.transcribe.side_effect = fake_transcribe
        video = tmp_path / "clip.mp4"
        video.touch()

        lines: list[str] = []
        transcribe_video(
            video, model=mock_transcribe.model, language=None, on_segment=lines.append
        )
        assert lines == []

    def test_on_file_progress_receives_fractions_of_known_duration(
        self, tmp_path, mock_transcribe, mocker
    ):
        mocker.patch("add_subs_to_videos.transcribe._probe_duration", return_value=10.0)

        def fake_transcribe(media, language="", new_segment_callback=None):
            for seg in mock_transcribe.raw_segs:
                new_segment_callback(seg)
            return mock_transcribe.raw_segs

        mock_transcribe.model.transcribe.side_effect = fake_transcribe
        video = tmp_path / "clip.mp4"
        video.touch()

        fractions: list[float] = []
        transcribe_video(
            video,
            model=mock_transcribe.model,
            language=None,
            on_file_progress=fractions.append,
        )
        assert fractions == [0.35, 0.6]

    def test_on_file_progress_clamped_to_one(self, tmp_path, mock_transcribe, mocker):
        mocker.patch("add_subs_to_videos.transcribe._probe_duration", return_value=1.0)

        def fake_transcribe(media, language="", new_segment_callback=None):
            new_segment_callback(mock_transcribe.raw_segs[1])  # t1 = 6.0s > duration
            return mock_transcribe.raw_segs

        mock_transcribe.model.transcribe.side_effect = fake_transcribe
        video = tmp_path / "clip.mp4"
        video.touch()

        fractions: list[float] = []
        transcribe_video(
            video,
            model=mock_transcribe.model,
            language=None,
            on_file_progress=fractions.append,
        )
        assert fractions == [1.0]

    def test_on_file_progress_not_called_when_duration_unknown(
        self, tmp_path, mock_transcribe, mocker
    ):
        mocker.patch("add_subs_to_videos.transcribe._probe_duration", return_value=None)

        def fake_transcribe(media, language="", new_segment_callback=None):
            for seg in mock_transcribe.raw_segs:
                new_segment_callback(seg)
            return mock_transcribe.raw_segs

        mock_transcribe.model.transcribe.side_effect = fake_transcribe
        video = tmp_path / "clip.mp4"
        video.touch()

        fractions: list[float] = []
        transcribe_video(
            video,
            model=mock_transcribe.model,
            language=None,
            on_file_progress=fractions.append,
        )
        assert fractions == []


# ---------------------------------------------------------------------------
# process_directory
# ---------------------------------------------------------------------------


_COMMON_KWARGS = dict(
    model_name="small",
    language=None,
    force=False,
    show_progress=False,
)


class _FakeBar:
    """Stand-in for tqdm that records `.n` at each refresh, without rendering."""

    def __init__(self, *args, **kwargs):
        self.n = 0
        self.n_history: list[float] = []

    def set_description(self, *args, **kwargs):
        pass

    def set_postfix(self, *args, **kwargs):
        pass

    def refresh(self):
        self.n_history.append(self.n)

    def reset(self):
        self.n = 0

    def close(self):
        pass


@pytest.fixture
def fake_tqdm(mocker):
    """Patches the tqdm bars in process_directory with `_FakeBar` instances.

    Returns the list of created bars in creation order: [outer "transcribing"
    bar, inner "file" bar].
    """
    created: list[_FakeBar] = []

    def make_bar(*args, **kwargs):
        bar = _FakeBar(*args, **kwargs)
        created.append(bar)
        return bar

    mocker.patch("add_subs_to_videos.transcribe.tqdm", side_effect=make_bar)
    return created


class TestDefaultNThreads:
    def test_falls_back_to_four_when_cpu_count_is_none(self, mocker):
        mocker.patch("add_subs_to_videos.transcribe.os.cpu_count", return_value=None)
        assert default_n_threads() == 4


class TestProcessDirectory:
    def test_no_videos_skips_model_load(self, tmp_path, mock_transcribe):
        process_directory(tmp_path, **_COMMON_KWARGS)
        mock_transcribe.model_cls.assert_not_called()

    def test_model_loaded_with_correct_name(self, tmp_path, mock_transcribe):
        (tmp_path / "clip.mp4").touch()
        process_directory(tmp_path, model_name="large-v3", language=None, force=False, show_progress=False)
        mock_transcribe.model_cls.assert_called_once_with("large-v3")

    def test_model_loaded_once_for_multiple_videos(self, tmp_video_dir, mock_transcribe):
        process_directory(tmp_video_dir, **_COMMON_KWARGS)
        mock_transcribe.model_cls.assert_called_once()

    def test_download_step_forwards_cancel_and_on_model_progress(self, tmp_path, mock_transcribe, mocker):
        (tmp_path / "clip.mp4").touch()
        mock_download = mocker.patch("add_subs_to_videos.transcribe._download_model")
        cancel = mocker.MagicMock()
        cancel.is_set.return_value = False
        on_model_progress = lambda d, t: None
        process_directory(
            tmp_path, **_COMMON_KWARGS, cancel=cancel, on_model_progress=on_model_progress
        )
        mock_download.assert_called_once_with(
            "small", show_progress=False, cancel=cancel, on_model_progress=on_model_progress
        )

    def test_cancelled_during_download_skips_model_load_without_exiting(
        self, tmp_path, mock_transcribe, mocker
    ):
        (tmp_path / "clip.mp4").touch()
        mocker.patch("add_subs_to_videos.transcribe._download_model", side_effect=_Cancelled)
        process_directory(tmp_path, **_COMMON_KWARGS)
        mock_transcribe.model_cls.assert_not_called()

    def test_download_failure_exits_without_loading_model(self, tmp_path, mock_transcribe, mocker):
        (tmp_path / "clip.mp4").touch()
        mocker.patch(
            "add_subs_to_videos.transcribe._download_model", side_effect=RuntimeError("boom")
        )
        with pytest.raises(SystemExit):
            process_directory(tmp_path, **_COMMON_KWARGS)
        mock_transcribe.model_cls.assert_not_called()

    def test_srt_written_next_to_video(self, tmp_path, mock_transcribe):
        video = tmp_path / "clip.mp4"
        video.touch()
        process_directory(tmp_path, **_COMMON_KWARGS)
        assert (tmp_path / "clip.srt").exists()

    def test_n_threads_defaults_to_cpu_count(self, tmp_path, mock_transcribe, mocker):
        mocker.patch("add_subs_to_videos.transcribe.os.cpu_count", return_value=6)
        (tmp_path / "clip.mp4").touch()
        process_directory(tmp_path, **_COMMON_KWARGS)
        assert mock_transcribe.model.transcribe.call_args.kwargs["n_threads"] == 6

    def test_n_threads_explicit_value_is_forwarded(self, tmp_path, mock_transcribe):
        (tmp_path / "clip.mp4").touch()
        process_directory(tmp_path, **_COMMON_KWARGS, n_threads=2)
        assert mock_transcribe.model.transcribe.call_args.kwargs["n_threads"] == 2

    def test_n_threads_above_core_count_is_capped(self, tmp_path, mock_transcribe, mocker, caplog):
        mocker.patch("add_subs_to_videos.transcribe.os.cpu_count", return_value=4)
        (tmp_path / "clip.mp4").touch()
        with caplog.at_level("WARNING"):
            process_directory(tmp_path, **_COMMON_KWARGS, n_threads=99)
        assert mock_transcribe.model.transcribe.call_args.kwargs["n_threads"] == 4
        assert "capping" in caplog.text

    def test_existing_srt_skipped_without_force(self, tmp_path, mock_transcribe):
        video = tmp_path / "clip.mp4"
        video.touch()
        srt = tmp_path / "clip.srt"
        srt.write_text("existing content", encoding="utf-8")

        process_directory(tmp_path, **_COMMON_KWARGS)

        mock_transcribe.model.transcribe.assert_not_called()
        assert srt.read_text(encoding="utf-8") == "existing content"

    def test_existing_srt_overwritten_with_force(self, tmp_path, mock_transcribe):
        video = tmp_path / "clip.mp4"
        video.touch()
        srt = tmp_path / "clip.srt"
        srt.write_text("old content", encoding="utf-8")

        process_directory(tmp_path, **{**_COMMON_KWARGS, "force": True})

        mock_transcribe.model.transcribe.assert_called_once()
        assert srt.read_text(encoding="utf-8") != "old content"

    def test_failed_file_does_not_abort_batch(self, tmp_path, mock_transcribe):
        (tmp_path / "a.mp4").touch()
        (tmp_path / "b.mp4").touch()

        mock_transcribe.model.transcribe.side_effect = [
            RuntimeError("transcribe failed"),
            mock_transcribe.raw_segs,
        ]

        with pytest.raises(SystemExit) as exc_info:
            process_directory(tmp_path, **_COMMON_KWARGS)

        assert exc_info.value.code == 1
        assert mock_transcribe.model.transcribe.call_count == 2

    def test_all_fail_exits_1(self, tmp_path, mock_transcribe):
        (tmp_path / "clip.mp4").touch()
        mock_transcribe.model.transcribe.side_effect = RuntimeError("boom")

        with pytest.raises(SystemExit) as exc_info:
            process_directory(tmp_path, **_COMMON_KWARGS)

        assert exc_info.value.code == 1

    def test_model_load_failure_exits_1_with_clean_error(self, tmp_path, mock_transcribe, caplog):
        (tmp_path / "clip.mp4").touch()
        mock_transcribe.model_cls.side_effect = RuntimeError("model not found")

        with caplog.at_level("ERROR"):
            with pytest.raises(SystemExit) as exc_info:
                process_directory(tmp_path, **_COMMON_KWARGS)

        assert exc_info.value.code == 1
        assert "model not found" in caplog.text
        mock_transcribe.model.transcribe.assert_not_called()

    def test_called_process_error_uses_ffmpeg_diagnostic(self, tmp_path, mock_transcribe, mocker, caplog):
        import subprocess

        (tmp_path / "clip.mp4").touch()
        mock_transcribe.model.transcribe.side_effect = subprocess.CalledProcessError(1, "ffmpeg")
        diag_result = mocker.MagicMock(stderr="Invalid data found when processing input\n")
        mocker.patch("add_subs_to_videos.transcribe.subprocess.run", return_value=diag_result)

        with caplog.at_level("WARNING", logger="root"), pytest.raises(SystemExit):
            process_directory(tmp_path, **_COMMON_KWARGS)

        assert "ffmpeg: Invalid data found when processing input" in caplog.text

    def test_warns_when_ffmpeg_missing(self, tmp_path, mock_transcribe, mocker, caplog):
        (tmp_path / "clip.mp4").touch()
        mocker.patch("add_subs_to_videos.transcribe.shutil.which", return_value=None)

        with caplog.at_level("WARNING", logger="root"):
            process_directory(tmp_path, **_COMMON_KWARGS)

        assert "ffmpeg not found on PATH" in caplog.text

    def test_logs_number_of_videos_found(self, tmp_video_dir, mock_transcribe, caplog):
        with caplog.at_level("INFO", logger="root"):
            process_directory(tmp_video_dir, **_COMMON_KWARGS)

        assert f"Found 3 video file(s) under {tmp_video_dir}" in caplog.text

    def test_done_log_includes_elapsed_seconds(self, tmp_path, mock_transcribe, caplog):
        (tmp_path / "clip.mp4").touch()

        with caplog.at_level("INFO", logger="root"):
            process_directory(tmp_path, **_COMMON_KWARGS)

        assert re.search(r"DONE\s+clip\.mp4 -> clip\.srt \(\d+\.\d+s\)", caplog.text)

    def test_all_succeed_no_exit(self, tmp_path, mock_transcribe):
        (tmp_path / "clip.mp4").touch()
        process_directory(tmp_path, **_COMMON_KWARGS)

    def test_multiple_videos_all_get_srt(self, tmp_path, mock_transcribe):
        for name in ("a.mp4", "b.mkv", "c.avi"):
            (tmp_path / name).touch()
        process_directory(tmp_path, **_COMMON_KWARGS)
        assert mock_transcribe.model.transcribe.call_count == 3
        for name in ("a.srt", "b.srt", "c.srt"):
            assert (tmp_path / name).exists()

    def test_summary_stdout_counts(self, tmp_path, mock_transcribe, capsys):
        (tmp_path / "clip.mp4").touch()
        process_directory(tmp_path, **_COMMON_KWARGS)
        out = capsys.readouterr().out
        assert "1 transcribed" in out
        assert "0 skipped" in out
        assert "0 failed" in out

    def test_skipped_reflected_in_summary(self, tmp_path, mock_transcribe, capsys):
        (tmp_path / "clip.mp4").touch()
        (tmp_path / "clip.srt").touch()
        process_directory(tmp_path, **_COMMON_KWARGS)
        out = capsys.readouterr().out
        assert "0 transcribed" in out
        assert "1 skipped" in out

    def test_cancel_stops_processing_between_files(self, tmp_path, mock_transcribe):
        import threading
        (tmp_path / "a.mp4").touch()
        (tmp_path / "b.mp4").touch()
        cancel = threading.Event()

        def transcribe_and_cancel(*args, **kwargs):
            cancel.set()
            return mock_transcribe.raw_segs

        mock_transcribe.model.transcribe.side_effect = transcribe_and_cancel
        process_directory(tmp_path, **_COMMON_KWARGS, cancel=cancel)

        assert mock_transcribe.model.transcribe.call_count == 1
        assert not (tmp_path / "b.srt").exists()

    def test_cancel_set_mid_transcription_stops_without_writing_srt(self, tmp_path, mock_transcribe):
        import threading
        (tmp_path / "a.mp4").touch()
        (tmp_path / "b.mp4").touch()
        cancel = threading.Event()

        def fake_transcribe(media, language="", new_segment_callback=None, **kwargs):
            cancel.set()
            new_segment_callback(mock_transcribe.raw_segs[0])
            return mock_transcribe.raw_segs

        mock_transcribe.model.transcribe.side_effect = fake_transcribe
        process_directory(tmp_path, **_COMMON_KWARGS, cancel=cancel)

        assert mock_transcribe.model.transcribe.call_count == 1
        assert not (tmp_path / "a.srt").exists()
        assert not (tmp_path / "b.srt").exists()

    def test_cancel_already_set_skips_all_files(self, tmp_path, mock_transcribe):
        import threading
        (tmp_path / "a.mp4").touch()
        cancel = threading.Event()
        cancel.set()
        process_directory(tmp_path, **_COMMON_KWARGS, cancel=cancel)
        mock_transcribe.model.transcribe.assert_not_called()

    def test_cancel_none_processes_normally(self, tmp_path, mock_transcribe):
        (tmp_path / "clip.mp4").touch()
        process_directory(tmp_path, **_COMMON_KWARGS, cancel=None)
        mock_transcribe.model.transcribe.assert_called_once()

    def test_show_progress_true_does_not_raise(self, tmp_path, mock_transcribe):
        (tmp_path / "clip.mp4").touch()
        process_directory(tmp_path, model_name="small", language=None, force=False, show_progress=True)

    def test_language_forwarded_to_model(self, tmp_path, mock_transcribe):
        video = tmp_path / "clip.mp4"
        video.touch()
        process_directory(tmp_path, model_name="small", language="es", force=False, show_progress=False)
        mock_transcribe.model.transcribe.assert_called_once()
        args, kwargs = mock_transcribe.model.transcribe.call_args
        assert args == (str(video),)
        assert kwargs["language"] == "es"

    def test_empty_transcription_writes_empty_srt(self, tmp_path, mock_transcribe):
        mock_transcribe.model.transcribe.return_value = []
        (tmp_path / "clip.mp4").touch()
        process_directory(tmp_path, **_COMMON_KWARGS)
        srt = tmp_path / "clip.srt"
        assert srt.exists()
        assert srt.read_text(encoding="utf-8") == ""

    def test_srt_content_matches_mock_segments(self, tmp_path, mock_transcribe):
        (tmp_path / "clip.mp4").touch()
        process_directory(tmp_path, **_COMMON_KWARGS)
        content = (tmp_path / "clip.srt").read_text(encoding="utf-8")
        assert "00:00:01,000 --> 00:00:03,500" in content
        assert "Hello world" in content
        assert "00:00:04,000 --> 00:00:06,000" in content
        assert "How are you" in content

    def test_srt_content_is_utf8(self, tmp_path, mock_transcribe):
        def make_seg(start, end, text):
            s = mock_transcribe.model.transcribe.return_value[0].__class__()
            s.t0 = int(start * 100)
            s.t1 = int(end * 100)
            s.text = text
            return s

        from unittest.mock import MagicMock
        seg = MagicMock()
        seg.t0 = 0
        seg.t1 = 100
        seg.text = "Héllo wörld"
        mock_transcribe.model.transcribe.return_value = [seg]

        (tmp_path / "clip.mp4").touch()
        process_directory(tmp_path, **_COMMON_KWARGS)
        content = (tmp_path / "clip.srt").read_text(encoding="utf-8")
        assert "Héllo wörld" in content

    def test_outer_bar_shows_continuous_combined_progress(
        self, tmp_path, mock_transcribe, mocker, fake_tqdm
    ):
        mocker.patch("add_subs_to_videos.transcribe._probe_duration", return_value=10.0)

        def fake_transcribe(media, language="", new_segment_callback=None, **kwargs):
            for seg in mock_transcribe.raw_segs:
                new_segment_callback(seg)
            return mock_transcribe.raw_segs

        mock_transcribe.model.transcribe.side_effect = fake_transcribe
        (tmp_path / "a.mp4").touch()
        (tmp_path / "b.mp4").touch()

        process_directory(tmp_path, model_name="small", language=None, force=False, show_progress=True)

        outer_bar, file_bar = fake_tqdm
        assert outer_bar.n_history == [0.0, 0.35, 0.6, 1.0, 1.0, 1.35, 1.6, 2.0]
        assert file_bar.n_history == [0.0, 35.0, 60.0, 100.0, 0.0, 35.0, 60.0, 100.0]

    def test_outer_bar_snaps_to_integer_on_skip_and_fail(
        self, tmp_path, mock_transcribe, fake_tqdm
    ):
        (tmp_path / "a.mp4").touch()
        (tmp_path / "a.srt").touch()
        (tmp_path / "b.mp4").touch()
        mock_transcribe.model.transcribe.side_effect = RuntimeError("boom")

        with pytest.raises(SystemExit):
            process_directory(tmp_path, model_name="small", language=None, force=False, show_progress=True)

        outer_bar, _file_bar = fake_tqdm
        assert outer_bar.n_history == [0.0, 1, 1.0, 2]
        assert outer_bar.n == 2

    def test_on_progress_emits_expected_event_sequence_for_mixed_outcomes(
        self, tmp_path, mock_transcribe
    ):
        ok = tmp_path / "a.mp4"
        ok.touch()
        skipped = tmp_path / "b.mp4"
        skipped.touch()
        (tmp_path / "b.srt").touch()
        failed = tmp_path / "c.mp4"
        failed.touch()

        mock_transcribe.model.transcribe.side_effect = [
            mock_transcribe.raw_segs,
            RuntimeError("boom"),
        ]

        events = []
        with pytest.raises(SystemExit):
            process_directory(tmp_path, **_COMMON_KWARGS, on_progress=events.append)

        stages = [(e.stage, e.index, e.video) for e in events]
        assert stages == [
            ("start", 1, ok),
            ("done", 1, ok),
            ("start", 2, skipped),
            ("skip", 2, skipped),
            ("start", 3, failed),
            ("fail", 3, failed),
            ("summary", 3, None),
        ]

        # `start` reflects the running counts *before* this file is accounted for;
        # `done`/`skip`/`fail` reflect the counts *after*.
        by_stage = {(e.stage, e.index): e for e in events}
        assert (by_stage[("start", 1)].done, by_stage[("start", 1)].skipped, by_stage[("start", 1)].failed) == (0, 0, 0)
        assert (by_stage[("done", 1)].done, by_stage[("done", 1)].skipped, by_stage[("done", 1)].failed) == (1, 0, 0)
        assert (by_stage[("start", 2)].done, by_stage[("start", 2)].skipped, by_stage[("start", 2)].failed) == (1, 0, 0)
        assert (by_stage[("skip", 2)].done, by_stage[("skip", 2)].skipped, by_stage[("skip", 2)].failed) == (1, 1, 0)
        assert (by_stage[("start", 3)].done, by_stage[("start", 3)].skipped, by_stage[("start", 3)].failed) == (1, 1, 0)
        assert (by_stage[("fail", 3)].done, by_stage[("fail", 3)].skipped, by_stage[("fail", 3)].failed) == (1, 1, 1)

        summary = events[-1]
        assert summary.total == 3
        assert (summary.done, summary.skipped, summary.failed) == (1, 1, 1)
        assert summary.elapsed is not None and summary.elapsed >= 0

    def test_on_progress_emits_summary_after_cancellation(self, tmp_path, mock_transcribe):
        import threading

        (tmp_path / "a.mp4").touch()
        (tmp_path / "b.mp4").touch()
        cancel = threading.Event()
        cancel.set()

        events = []
        process_directory(tmp_path, **_COMMON_KWARGS, cancel=cancel, on_progress=events.append)

        assert [e.stage for e in events] == ["summary"]
        summary = events[0]
        assert summary.video is None
        assert summary.index == summary.total == 2
        assert (summary.done, summary.skipped, summary.failed) == (0, 0, 0)


# ---------------------------------------------------------------------------
# model_file_path / is_model_downloaded
# ---------------------------------------------------------------------------


class TestModelFilePath:
    def test_uses_models_dir_and_ggml_prefix(self, mocker, tmp_path):
        mocker.patch("add_subs_to_videos.transcribe.MODELS_DIR", tmp_path)
        assert model_file_path("small") == tmp_path / "ggml-small.bin"


class TestIsModelDownloaded:
    def test_false_when_file_missing(self, mocker, tmp_path):
        mocker.patch("add_subs_to_videos.transcribe.MODELS_DIR", tmp_path)
        assert is_model_downloaded("small") is False

    def test_true_when_file_present(self, mocker, tmp_path):
        mocker.patch("add_subs_to_videos.transcribe.MODELS_DIR", tmp_path)
        (tmp_path / "ggml-small.bin").write_bytes(b"x")
        assert is_model_downloaded("small") is True


# ---------------------------------------------------------------------------
# _download_model
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, chunks, total=0):
        self._chunks = chunks
        self.headers = {"content-length": str(total)} if total else {}

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=None):
        yield from self._chunks


class TestDownloadModel:
    def test_skips_download_when_file_already_exists(self, mocker, tmp_path):
        mocker.patch("add_subs_to_videos.transcribe.MODELS_DIR", tmp_path)
        (tmp_path / "ggml-small.bin").write_bytes(b"already here")
        mock_get = mocker.patch("add_subs_to_videos.transcribe.requests.get")
        _download_model("small")
        mock_get.assert_not_called()

    def test_skips_download_for_unknown_model_name(self, mocker, tmp_path):
        mocker.patch("add_subs_to_videos.transcribe.MODELS_DIR", tmp_path)
        mock_get = mocker.patch("add_subs_to_videos.transcribe.requests.get")
        _download_model("not-a-real-model")
        mock_get.assert_not_called()

    def test_writes_chunks_and_reports_start_and_final_progress(self, mocker, tmp_path):
        mocker.patch("add_subs_to_videos.transcribe.MODELS_DIR", tmp_path)
        chunks = [b"a" * 5, b"b" * 5]
        mocker.patch(
            "add_subs_to_videos.transcribe.requests.get",
            return_value=_FakeResponse(chunks, total=10),
        )
        progress = []
        _download_model(
            "small", show_progress=False, on_model_progress=lambda d, t: progress.append((d, t))
        )

        assert (tmp_path / "ggml-small.bin").read_bytes() == b"a" * 5 + b"b" * 5
        assert progress[0] == (0, 10)
        assert progress[-1] == (10, 10)

    def test_unknown_total_size_reports_zero(self, mocker, tmp_path):
        mocker.patch("add_subs_to_videos.transcribe.MODELS_DIR", tmp_path)
        mocker.patch(
            "add_subs_to_videos.transcribe.requests.get",
            return_value=_FakeResponse([b"a" * 5], total=0),
        )
        progress = []
        _download_model(
            "small", show_progress=False, on_model_progress=lambda d, t: progress.append((d, t))
        )
        assert all(total == 0 for _downloaded, total in progress)

    def test_keeps_partial_file_on_download_error_for_resuming(self, mocker, tmp_path):
        mocker.patch("add_subs_to_videos.transcribe.MODELS_DIR", tmp_path)

        def bad_iter_content(chunk_size=None):
            yield b"a" * 5
            raise RuntimeError("network drop")

        fake_resp = mocker.MagicMock()
        fake_resp.headers = {"content-length": "100"}
        fake_resp.iter_content.side_effect = bad_iter_content
        mocker.patch("add_subs_to_videos.transcribe.requests.get", return_value=fake_resp)

        with pytest.raises(RuntimeError):
            _download_model("small", show_progress=False)

        assert not (tmp_path / "ggml-small.bin").exists()
        assert (tmp_path / "ggml-small.bin.part").read_bytes() == b"a" * 5

    def test_cancel_mid_download_keeps_partial_file_for_resuming(self, mocker, tmp_path):
        import threading

        mocker.patch("add_subs_to_videos.transcribe.MODELS_DIR", tmp_path)
        cancel = threading.Event()

        def chunks_then_cancel(chunk_size=None):
            yield b"a" * 5
            cancel.set()
            yield b"b" * 5

        fake_resp = mocker.MagicMock()
        fake_resp.headers = {"content-length": "10"}
        fake_resp.iter_content.side_effect = chunks_then_cancel
        mocker.patch("add_subs_to_videos.transcribe.requests.get", return_value=fake_resp)

        with pytest.raises(_Cancelled):
            _download_model("small", show_progress=False, cancel=cancel)

        assert not (tmp_path / "ggml-small.bin").exists()
        assert (tmp_path / "ggml-small.bin.part").read_bytes() == b"a" * 5

    def test_raises_and_keeps_partial_file_when_download_ends_early(self, mocker, tmp_path):
        mocker.patch("add_subs_to_videos.transcribe.MODELS_DIR", tmp_path)
        mocker.patch(
            "add_subs_to_videos.transcribe.requests.get",
            return_value=_FakeResponse([b"a" * 5], total=10),
        )
        with pytest.raises(OSError):
            _download_model("small", show_progress=False)
        assert not (tmp_path / "ggml-small.bin").exists()
        assert (tmp_path / "ggml-small.bin.part").read_bytes() == b"a" * 5

    def test_resumes_from_existing_partial_file_with_range_request(self, mocker, tmp_path):
        mocker.patch("add_subs_to_videos.transcribe.MODELS_DIR", tmp_path)
        (tmp_path / "ggml-small.bin.part").write_bytes(b"a" * 5)

        fake_resp = mocker.MagicMock()
        fake_resp.status_code = 206
        fake_resp.headers = {"content-length": "5"}
        fake_resp.iter_content.return_value = iter([b"b" * 5])
        mock_get = mocker.patch("add_subs_to_videos.transcribe.requests.get", return_value=fake_resp)

        progress = []
        _download_model(
            "small", show_progress=False, on_model_progress=lambda d, t: progress.append((d, t))
        )

        assert mock_get.call_args.kwargs["headers"] == {"Range": "bytes=5-"}
        assert (tmp_path / "ggml-small.bin").read_bytes() == b"a" * 5 + b"b" * 5
        assert not (tmp_path / "ggml-small.bin.part").exists()
        assert progress[0] == (5, 10)
        assert progress[-1] == (10, 10)

    def test_restarts_from_scratch_when_server_ignores_range_request(self, mocker, tmp_path):
        mocker.patch("add_subs_to_videos.transcribe.MODELS_DIR", tmp_path)
        (tmp_path / "ggml-small.bin.part").write_bytes(b"stale-partial-data")

        fake_resp = mocker.MagicMock()
        fake_resp.status_code = 200  # server doesn't support range requests
        fake_resp.headers = {"content-length": "5"}
        fake_resp.iter_content.return_value = iter([b"c" * 5])
        mocker.patch("add_subs_to_videos.transcribe.requests.get", return_value=fake_resp)

        _download_model("small", show_progress=False)

        assert (tmp_path / "ggml-small.bin").read_bytes() == b"c" * 5

    def test_416_response_treats_existing_partial_file_as_complete(self, mocker, tmp_path):
        mocker.patch("add_subs_to_videos.transcribe.MODELS_DIR", tmp_path)
        (tmp_path / "ggml-small.bin.part").write_bytes(b"a" * 10)

        fake_resp = mocker.MagicMock()
        fake_resp.status_code = 416
        mock_get = mocker.patch("add_subs_to_videos.transcribe.requests.get", return_value=fake_resp)

        _download_model("small", show_progress=False)

        assert mock_get.call_args.kwargs["headers"] == {"Range": "bytes=10-"}
        fake_resp.close.assert_called_once()
        assert (tmp_path / "ggml-small.bin").read_bytes() == b"a" * 10
        assert not (tmp_path / "ggml-small.bin.part").exists()
