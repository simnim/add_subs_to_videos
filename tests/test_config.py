from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from add_subs_to_videos.config import config_path, load_config, save_config


# ---------------------------------------------------------------------------
# config_path
# ---------------------------------------------------------------------------


class TestConfigPath:
    def test_default_uses_home_config(self, monkeypatch):
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        p = config_path()
        assert p == Path.home() / ".config" / "add-subs-to-videos" / "config.toml"

    def test_respects_xdg_config_home(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        p = config_path()
        assert p == tmp_path / "add-subs-to-videos" / "config.toml"


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------


class TestLoadConfig:
    def test_missing_file_returns_empty_dict(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        assert load_config() == {}

    def test_returns_known_keys(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        cfg_file = tmp_path / "add-subs-to-videos" / "config.toml"
        cfg_file.parent.mkdir(parents=True)
        cfg_file.write_text('model = "large-v3"\nlanguage = "en"\n', encoding="utf-8")
        result = load_config()
        assert result == {"model": "large-v3", "language": "en"}

    def test_filters_unknown_keys(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        cfg_file = tmp_path / "add-subs-to-videos" / "config.toml"
        cfg_file.parent.mkdir(parents=True)
        cfg_file.write_text('model = "small"\nunknown_key = "ignored"\n', encoding="utf-8")
        result = load_config()
        assert "unknown_key" not in result
        assert result["model"] == "small"

    def test_directory_key_loaded(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        cfg_file = tmp_path / "add-subs-to-videos" / "config.toml"
        cfg_file.parent.mkdir(parents=True)
        cfg_file.write_text(f'directory = "{tmp_path}"\n', encoding="utf-8")
        assert load_config()["directory"] == str(tmp_path)

    def test_partial_keys_ok(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        cfg_file = tmp_path / "add-subs-to-videos" / "config.toml"
        cfg_file.parent.mkdir(parents=True)
        cfg_file.write_text('model = "tiny"\n', encoding="utf-8")
        result = load_config()
        assert result == {"model": "tiny"}
        assert "language" not in result
        assert "directory" not in result

    def test_malformed_toml_raises(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        cfg_file = tmp_path / "add-subs-to-videos" / "config.toml"
        cfg_file.parent.mkdir(parents=True)
        cfg_file.write_text("this is not valid toml !!!\n", encoding="utf-8")
        with pytest.raises(tomllib.TOMLDecodeError):
            load_config()


# ---------------------------------------------------------------------------
# save_config
# ---------------------------------------------------------------------------


class TestSaveConfig:
    def test_creates_directory_and_file(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        save_config({"model": "small"})
        assert config_path().exists()

    def test_written_file_is_valid_toml(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        save_config({"model": "base", "language": "fr"})
        with config_path().open("rb") as f:
            data = tomllib.load(f)
        assert data["model"] == "base"
        assert data["language"] == "fr"

    def test_round_trip(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        original = {"model": "large-v3", "language": "de", "directory": "/videos"}
        save_config(original)
        assert load_config() == original

    def test_merges_with_existing(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        save_config({"model": "tiny"})
        save_config({"language": "ja"})
        result = load_config()
        assert result["model"] == "tiny"
        assert result["language"] == "ja"

    def test_update_overwrites_existing_key(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        save_config({"model": "tiny"})
        save_config({"model": "large-v3"})
        assert load_config()["model"] == "large-v3"

    def test_ignores_unknown_keys(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        save_config({"model": "small", "force": True, "bogus": "x"})
        result = load_config()
        assert "force" not in result
        assert "bogus" not in result

    def test_empty_string_not_written(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        save_config({"model": "small", "language": ""})
        result = load_config()
        assert "language" not in result

    def test_none_value_not_written(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        save_config({"model": "small", "language": None})
        result = load_config()
        assert "language" not in result

    def test_empty_updates_preserves_existing(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        save_config({"model": "tiny"})
        save_config({})
        assert load_config()["model"] == "tiny"

    def test_keys_written_in_sorted_order(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        save_config({"model": "tiny", "language": "en", "directory": "/vids"})
        lines = config_path().read_text(encoding="utf-8").strip().splitlines()
        keys = [line.split(" =")[0] for line in lines]
        assert keys == sorted(keys)

    def test_three_sequential_saves_accumulate_all_keys(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        save_config({"model": "tiny"})
        save_config({"language": "en"})
        save_config({"directory": "/videos"})
        assert load_config() == {"model": "tiny", "language": "en", "directory": "/videos"}

    def test_all_unknown_keys_gives_empty_load(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        cfg_file = tmp_path / "add-subs-to-videos" / "config.toml"
        cfg_file.parent.mkdir(parents=True)
        cfg_file.write_text('foo = "bar"\nbaz = "qux"\n', encoding="utf-8")
        assert load_config() == {}
