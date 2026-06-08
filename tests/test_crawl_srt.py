from __future__ import annotations

from pathlib import Path

import pytest

from add_subs_to_videos.cli import build_parser
from add_subs_to_videos.files import VIDEO_EXTENSIONS, find_videos
from add_subs_to_videos.srt import format_srt_timestamp, segments_to_srt
from add_subs_to_videos.transcribe import (
    _Cancelled,
    _probe_duration,
    _raw_to_dicts,
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

    def test_returns_none_when_ffprobe_missing(self, tmp_path, mocker):
        mocker.patch(
            "add_subs_to_videos.transcribe.subprocess.run", side_effect=FileNotFoundError
        )
        assert _probe_duration(tmp_path / "clip.mp4") is None

    def test_returns_none_when_ffprobe_fails(self, tmp_path, mocker):
        import subprocess

        mocker.patch(
            "add_subs_to_videos.transcribe.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "ffprobe"),
        )
        assert _probe_duration(tmp_path / "clip.mp4") is None

    def test_returns_none_when_output_is_not_a_number(self, tmp_path, mocker):
        result = mocker.MagicMock(stdout="N/A\n")
        mocker.patch("add_subs_to_videos.transcribe.subprocess.run", return_value=result)
        assert _probe_duration(tmp_path / "clip.mp4") is None


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

    def test_srt_written_next_to_video(self, tmp_path, mock_transcribe):
        video = tmp_path / "clip.mp4"
        video.touch()
        process_directory(tmp_path, **_COMMON_KWARGS)
        assert (tmp_path / "clip.srt").exists()

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

        def fake_transcribe(media, language="", new_segment_callback=None):
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
        mock_transcribe.model.transcribe.assert_called_once_with(str(video), language="es")

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
