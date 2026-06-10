from __future__ import annotations

from pathlib import Path

import pytest

from add_subs_to_videos.cli import main


# All tests patch load_config and process_directory so nothing hits disk or
# the model. sys.argv is patched to control what the parser sees.


@pytest.fixture
def mock_pd(mocker):
    return mocker.patch("add_subs_to_videos.cli.process_directory")


@pytest.fixture
def no_config(mocker):
    return mocker.patch("add_subs_to_videos.cli.load_config", return_value={})


@pytest.fixture
def argv(mocker):
    def _set(*args):
        mocker.patch("sys.argv", ["prog", *args])
    return _set


class TestMainDirectoryHandling:
    def test_no_directory_no_config_exits_2(self, mocker, mock_pd, no_config):
        mocker.patch("sys.argv", ["prog"])
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 2

    def test_cli_directory_passed_as_path(self, tmp_path, mocker, mock_pd, no_config):
        mocker.patch("sys.argv", ["prog", str(tmp_path)])
        main()
        assert mock_pd.call_args[0][0] == tmp_path
        assert isinstance(mock_pd.call_args[0][0], Path)

    def test_directory_from_config_string_coerced_to_path(self, tmp_path, mocker, mock_pd):
        mocker.patch("sys.argv", ["prog"])
        mocker.patch("add_subs_to_videos.cli.load_config", return_value={"directory": str(tmp_path)})
        main()
        arg = mock_pd.call_args[0][0]
        assert arg == tmp_path
        assert isinstance(arg, Path)

    def test_cli_directory_beats_config_directory(self, tmp_path, mocker, mock_pd):
        other = tmp_path / "other"
        other.mkdir()
        mocker.patch("sys.argv", ["prog", str(tmp_path)])
        mocker.patch("add_subs_to_videos.cli.load_config", return_value={"directory": str(other)})
        main()
        assert mock_pd.call_args[0][0] == tmp_path


class TestMainModelHandling:
    def test_default_model_is_medium(self, tmp_path, mocker, mock_pd, no_config):
        mocker.patch("sys.argv", ["prog", str(tmp_path)])
        main()
        assert mock_pd.call_args.kwargs["model_name"] == "medium"

    def test_config_model_overrides_default(self, tmp_path, mocker, mock_pd):
        mocker.patch("sys.argv", ["prog", str(tmp_path)])
        mocker.patch("add_subs_to_videos.cli.load_config", return_value={"model": "large-v3"})
        main()
        assert mock_pd.call_args.kwargs["model_name"] == "large-v3"

    def test_cli_model_beats_config(self, tmp_path, mocker, mock_pd):
        mocker.patch("sys.argv", ["prog", str(tmp_path), "--model", "tiny"])
        mocker.patch("add_subs_to_videos.cli.load_config", return_value={"model": "large-v3"})
        main()
        assert mock_pd.call_args.kwargs["model_name"] == "tiny"


class TestMainLanguageHandling:
    def test_default_language_is_none(self, tmp_path, mocker, mock_pd, no_config):
        mocker.patch("sys.argv", ["prog", str(tmp_path)])
        main()
        assert mock_pd.call_args.kwargs["language"] is None

    def test_config_language_used(self, tmp_path, mocker, mock_pd):
        mocker.patch("sys.argv", ["prog", str(tmp_path)])
        mocker.patch("add_subs_to_videos.cli.load_config", return_value={"language": "de"})
        main()
        assert mock_pd.call_args.kwargs["language"] == "de"

    def test_cli_language_beats_config(self, tmp_path, mocker, mock_pd):
        mocker.patch("sys.argv", ["prog", str(tmp_path), "--language", "en"])
        mocker.patch("add_subs_to_videos.cli.load_config", return_value={"language": "de"})
        main()
        assert mock_pd.call_args.kwargs["language"] == "en"


class TestMainFlags:
    def test_force_defaults_false(self, tmp_path, mocker, mock_pd, no_config):
        mocker.patch("sys.argv", ["prog", str(tmp_path)])
        main()
        assert mock_pd.call_args.kwargs["force"] is False

    def test_force_flag_passed(self, tmp_path, mocker, mock_pd, no_config):
        mocker.patch("sys.argv", ["prog", str(tmp_path), "--force"])
        main()
        assert mock_pd.call_args.kwargs["force"] is True

    def test_show_progress_true_by_default(self, tmp_path, mocker, mock_pd, no_config):
        mocker.patch("sys.argv", ["prog", str(tmp_path)])
        main()
        assert mock_pd.call_args.kwargs["show_progress"] is True

    def test_quiet_disables_progress(self, tmp_path, mocker, mock_pd, no_config):
        mocker.patch("sys.argv", ["prog", str(tmp_path), "--quiet"])
        main()
        assert mock_pd.call_args.kwargs["show_progress"] is False

    def test_tilde_in_config_directory_expanded(self, mocker, mock_pd):
        mocker.patch("sys.argv", ["prog"])
        mocker.patch("add_subs_to_videos.cli.load_config", return_value={"directory": "~"})
        main()
        assert mock_pd.call_args[0][0] == Path.home()


class TestMainBundledFfmpeg:
    def test_main_calls_ensure_bundled_ffmpeg_on_path(self, tmp_path, mocker, mock_pd, no_config):
        ensure = mocker.patch("add_subs_to_videos.cli.ensure_bundled_ffmpeg_on_path")
        mocker.patch("sys.argv", ["prog", str(tmp_path)])
        main()
        ensure.assert_called_once()
