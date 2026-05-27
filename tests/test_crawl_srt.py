from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

import add_subs_to_videos.device as _device_mod
from add_subs_to_videos.cli import build_parser
from add_subs_to_videos.device import detect_device, resolve_hf_token
from add_subs_to_videos.files import VIDEO_EXTENSIONS, find_videos
from add_subs_to_videos.srt import format_srt_timestamp, segments_to_srt
from add_subs_to_videos.transcribe import process_directory, transcribe_video


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
        segs = [{"start": 0.0, "end": 1.0, "text": "   ", "speaker": "SPEAKER_00"}]
        assert segments_to_srt(segs) == ""

    def test_single_segment(self):
        segs = [{"start": 1.0, "end": 3.5, "text": "Hello world", "speaker": "SPEAKER_00"}]
        result = segments_to_srt(segs)
        assert result == (
            "1\n"
            "00:00:01,000 --> 00:00:03,500\n"
            "SPEAKER_00: Hello world\n"
        )

    def test_missing_speaker_falls_back_to_unknown(self):
        segs = [{"start": 0.5, "end": 1.5, "text": "No speaker here"}]
        result = segments_to_srt(segs)
        assert "UNKNOWN: No speaker here" in result

    def test_multiple_segments_sequential_index(self):
        segs = [
            {"start": 0.0, "end": 1.0, "text": "First", "speaker": "SPEAKER_00"},
            {"start": 1.5, "end": 2.5, "text": "Second", "speaker": "SPEAKER_01"},
        ]
        result = segments_to_srt(segs)
        lines = result.split("\n")
        assert lines[0] == "1"
        assert lines[4] == "2"

    def test_blank_line_between_cues(self):
        segs = [
            {"start": 0.0, "end": 1.0, "text": "First", "speaker": "SPEAKER_00"},
            {"start": 1.5, "end": 2.5, "text": "Second", "speaker": "SPEAKER_01"},
        ]
        result = segments_to_srt(segs)
        # Each cue block ends with a blank line (empty string between cues)
        assert "\n\n" in result

    def test_empty_segments_do_not_consume_index(self):
        segs = [
            {"start": 0.0, "end": 1.0, "text": "  ", "speaker": "SPEAKER_00"},
            {"start": 1.5, "end": 2.5, "text": "Second", "speaker": "SPEAKER_01"},
        ]
        result = segments_to_srt(segs)
        # Only one cue, and it must have index 1
        assert result.startswith("1\n")
        assert "2\n" not in result

    def test_text_is_stripped(self):
        segs = [{"start": 0.0, "end": 1.0, "text": "  padded  ", "speaker": "SPEAKER_00"}]
        result = segments_to_srt(segs)
        assert "SPEAKER_00: padded" in result
        assert "  padded  " not in result

    def test_comma_used_as_ms_separator(self):
        segs = [{"start": 1.5, "end": 2.5, "text": "Check", "speaker": "SPEAKER_00"}]
        result = segments_to_srt(segs)
        assert "," in result
        # The timestamp line must use comma, not period
        timestamp_line = result.split("\n")[1]
        assert "." not in timestamp_line


# ---------------------------------------------------------------------------
# build_parser
# ---------------------------------------------------------------------------


class TestBuildParser:
    def test_missing_model_exits(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["/some/dir"])

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

    def test_batch_size_defaults_to_16(self):
        parser = build_parser()
        args = parser.parse_args(["/some/dir", "--model", "small"])
        assert args.batch_size == 16

    def test_batch_size_override(self):
        parser = build_parser()
        args = parser.parse_args(["/some/dir", "--model", "small", "--batch-size", "4"])
        assert args.batch_size == 4

    def test_language_defaults_to_none(self):
        parser = build_parser()
        args = parser.parse_args(["/some/dir", "--model", "small"])
        assert args.language is None

    def test_language_set(self):
        parser = build_parser()
        args = parser.parse_args(["/some/dir", "--model", "small", "--language", "en"])
        assert args.language == "en"

    def test_hf_token_stored_as_hf_token(self):
        parser = build_parser()
        args = parser.parse_args(["/some/dir", "--model", "small", "--hf-token", "hf_abc"])
        assert args.hf_token == "hf_abc"

    def test_hf_token_defaults_to_none(self):
        parser = build_parser()
        args = parser.parse_args(["/some/dir", "--model", "small"])
        assert args.hf_token is None


# ---------------------------------------------------------------------------
# resolve_hf_token
# ---------------------------------------------------------------------------


class TestResolveHfToken:
    def test_cli_token_returned(self, monkeypatch):
        monkeypatch.delenv("HUGGINGFACE_TOKEN", raising=False)
        assert resolve_hf_token("hf_cli") == "hf_cli"

    def test_env_var_used_when_cli_is_none(self, monkeypatch):
        monkeypatch.setenv("HUGGINGFACE_TOKEN", "hf_env")
        assert resolve_hf_token(None) == "hf_env"

    def test_cli_wins_over_env_var(self, monkeypatch):
        monkeypatch.setenv("HUGGINGFACE_TOKEN", "hf_env")
        assert resolve_hf_token("hf_cli") == "hf_cli"

    def test_neither_provided_exits(self, monkeypatch):
        monkeypatch.delenv("HUGGINGFACE_TOKEN", raising=False)
        with pytest.raises(SystemExit):
            resolve_hf_token(None)

    def test_empty_cli_falls_through_to_env(self, monkeypatch):
        # Empty string is falsy — env var should be used
        monkeypatch.setenv("HUGGINGFACE_TOKEN", "hf_env")
        assert resolve_hf_token("") == "hf_env"


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

    def test_non_directory_path_exits(self, tmp_path):
        f = tmp_path / "file.mp4"
        f.touch()
        with pytest.raises(SystemExit):
            find_videos(f)

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
# detect_device
# ---------------------------------------------------------------------------


class TestDetectDevice:
    def test_cuda_available(self, mocker):
        torch_mock = mocker.MagicMock()
        torch_mock.cuda.is_available.return_value = True
        mocker.patch.dict(sys.modules, {"torch": torch_mock})
        import importlib
        importlib.reload(_device_mod)
        device, compute_type = _device_mod.detect_device()
        assert device == "cuda"
        assert compute_type == "float16"

    def test_mps_available(self, mocker):
        torch_mock = mocker.MagicMock()
        torch_mock.cuda.is_available.return_value = False
        torch_mock.backends.mps.is_available.return_value = True
        mocker.patch.dict(sys.modules, {"torch": torch_mock})
        import importlib
        importlib.reload(_device_mod)
        device, compute_type = _device_mod.detect_device()
        assert device == "mps"
        assert compute_type == "float32"

    def test_cpu_fallback(self, mocker):
        torch_mock = mocker.MagicMock()
        torch_mock.cuda.is_available.return_value = False
        torch_mock.backends.mps.is_available.return_value = False
        mocker.patch.dict(sys.modules, {"torch": torch_mock})
        import importlib
        importlib.reload(_device_mod)
        device, compute_type = _device_mod.detect_device()
        assert device == "cpu"
        assert compute_type == "int8"

    def test_torch_import_error_falls_back_to_cpu(self, mocker):
        mocker.patch.dict(sys.modules, {"torch": None})
        import importlib
        importlib.reload(_device_mod)
        device, compute_type = _device_mod.detect_device()
        assert device == "cpu"
        assert compute_type == "int8"


# ---------------------------------------------------------------------------
# transcribe_video
# ---------------------------------------------------------------------------


class TestTranscribeVideo:
    def test_returns_srt_string(self, tmp_path, mock_whisperx):
        video = tmp_path / "clip.mp4"
        video.touch()
        result = transcribe_video(
            video, model=mock_whisperx.model, device="cpu",
            hf_token="hf_tok", language=None, batch_size=16,
        )
        assert isinstance(result, str)
        assert "SPEAKER_00" in result

    def test_pipeline_call_order(self, tmp_path, mock_whisperx):
        video = tmp_path / "clip.mp4"
        video.touch()
        transcribe_video(
            video, model=mock_whisperx.model, device="cpu",
            hf_token="hf_tok", language=None, batch_size=16,
        )
        mock_whisperx.load_audio.assert_called_once_with(str(video))
        mock_whisperx.model.transcribe.assert_called_once()
        mock_whisperx.load_align_model.assert_called_once()
        mock_whisperx.align.assert_called_once()
        mock_whisperx.DiarizationPipeline.assert_called_once()
        mock_whisperx.assign_word_speakers.assert_called_once()

    def test_language_passed_to_transcribe(self, tmp_path, mock_whisperx):
        video = tmp_path / "clip.mp4"
        video.touch()
        transcribe_video(
            video, model=mock_whisperx.model, device="cpu",
            hf_token="hf_tok", language="fr", batch_size=16,
        )
        _, kwargs = mock_whisperx.model.transcribe.call_args
        assert kwargs.get("language") == "fr"

    def test_language_none_passed_through(self, tmp_path, mock_whisperx):
        video = tmp_path / "clip.mp4"
        video.touch()
        transcribe_video(
            video, model=mock_whisperx.model, device="cpu",
            hf_token="hf_tok", language=None, batch_size=16,
        )
        _, kwargs = mock_whisperx.model.transcribe.call_args
        assert kwargs.get("language") is None

    def test_hf_token_forwarded_to_diarization(self, tmp_path, mock_whisperx):
        video = tmp_path / "clip.mp4"
        video.touch()
        transcribe_video(
            video, model=mock_whisperx.model, device="cpu",
            hf_token="hf_secret", language=None, batch_size=16,
        )
        mock_whisperx.DiarizationPipeline.assert_called_once_with(
            use_auth_token="hf_secret", device="cpu"
        )

    def test_batch_size_forwarded_to_transcribe(self, tmp_path, mock_whisperx):
        video = tmp_path / "clip.mp4"
        video.touch()
        transcribe_video(
            video, model=mock_whisperx.model, device="cpu",
            hf_token="hf_tok", language=None, batch_size=4,
        )
        _, kwargs = mock_whisperx.model.transcribe.call_args
        assert kwargs.get("batch_size") == 4


# ---------------------------------------------------------------------------
# process_directory
# ---------------------------------------------------------------------------


_COMMON_KWARGS = dict(
    model_name="small",
    device="cpu",
    compute_type="int8",
    hf_token="hf_tok",
    language=None,
    force=False,
    batch_size=16,
)


class TestProcessDirectory:
    def test_no_videos_skips_model_load(self, tmp_path, mock_whisperx):
        process_directory(tmp_path, **_COMMON_KWARGS)
        mock_whisperx.load_model.assert_not_called()

    def test_model_loaded_once_for_multiple_videos(self, tmp_video_dir, mock_whisperx):
        process_directory(tmp_video_dir, **_COMMON_KWARGS)
        mock_whisperx.load_model.assert_called_once()

    def test_srt_written_next_to_video(self, tmp_path, mock_whisperx):
        video = tmp_path / "clip.mp4"
        video.touch()
        process_directory(tmp_path, **_COMMON_KWARGS)
        assert (tmp_path / "clip.srt").exists()

    def test_existing_srt_skipped_without_force(self, tmp_path, mock_whisperx):
        video = tmp_path / "clip.mp4"
        video.touch()
        srt = tmp_path / "clip.srt"
        srt.write_text("existing content", encoding="utf-8")

        process_directory(tmp_path, **_COMMON_KWARGS)

        mock_whisperx.load_audio.assert_not_called()
        assert srt.read_text(encoding="utf-8") == "existing content"

    def test_existing_srt_overwritten_with_force(self, tmp_path, mock_whisperx):
        video = tmp_path / "clip.mp4"
        video.touch()
        srt = tmp_path / "clip.srt"
        srt.write_text("old content", encoding="utf-8")

        process_directory(tmp_path, **{**_COMMON_KWARGS, "force": True})

        mock_whisperx.load_audio.assert_called_once()
        assert srt.read_text(encoding="utf-8") != "old content"

    def test_failed_file_does_not_abort_batch(self, tmp_path, mock_whisperx):
        (tmp_path / "a.mp4").touch()
        (tmp_path / "b.mp4").touch()

        call_count = 0

        def fail_on_first(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("audio decode failed")
            return b"audio"

        mock_whisperx.load_audio.side_effect = fail_on_first

        with pytest.raises(SystemExit) as exc_info:
            process_directory(tmp_path, **_COMMON_KWARGS)

        assert exc_info.value.code == 1
        # The second file should still have been attempted
        assert call_count == 2

    def test_all_fail_exits_1(self, tmp_path, mock_whisperx):
        (tmp_path / "clip.mp4").touch()
        mock_whisperx.load_audio.side_effect = RuntimeError("boom")

        with pytest.raises(SystemExit) as exc_info:
            process_directory(tmp_path, **_COMMON_KWARGS)

        assert exc_info.value.code == 1

    def test_all_succeed_no_exit(self, tmp_path, mock_whisperx):
        (tmp_path / "clip.mp4").touch()
        # Should return normally (no SystemExit)
        process_directory(tmp_path, **_COMMON_KWARGS)

    def test_srt_content_is_utf8(self, tmp_path, mock_whisperx):
        # Inject a segment with non-ASCII text
        mock_whisperx.assign_word_speakers.return_value = {
            "segments": [{"start": 0.0, "end": 1.0, "text": "Héllo wörld", "speaker": "SPEAKER_00"}]
        }
        (tmp_path / "clip.mp4").touch()
        process_directory(tmp_path, **_COMMON_KWARGS)
        content = (tmp_path / "clip.srt").read_text(encoding="utf-8")
        assert "Héllo wörld" in content
