from __future__ import annotations

import os
import sys

from add_subs_to_videos.runtime_paths import ensure_bundled_ffmpeg_on_path


def test_noop_when_not_frozen_and_no_snap(mocker):
    mocker.patch.object(sys, "frozen", False, create=True)
    mocker.patch.dict(os.environ, {"PATH": "/usr/bin"}, clear=True)
    ensure_bundled_ffmpeg_on_path()
    assert os.environ.get("PATH") == "/usr/bin"


def test_prepends_ffmpeg_bin_when_present(tmp_path, mocker):
    exe_dir = tmp_path / "MacOS"
    (exe_dir / "ffmpeg-bin").mkdir(parents=True)
    executable = exe_dir / "Add Subs to Videos"
    executable.touch()

    mocker.patch.object(sys, "frozen", True, create=True)
    mocker.patch.object(sys, "executable", str(executable))
    mocker.patch.dict(os.environ, {"PATH": "/usr/bin"}, clear=True)

    ensure_bundled_ffmpeg_on_path()

    path_entries = os.environ["PATH"].split(os.pathsep)
    assert str(exe_dir / "ffmpeg-bin") == path_entries[0]
    assert "/usr/bin" in path_entries


def test_noop_when_ffmpeg_bin_missing(tmp_path, mocker):
    exe_dir = tmp_path / "MacOS"
    exe_dir.mkdir(parents=True)
    executable = exe_dir / "Add Subs to Videos"
    executable.touch()

    mocker.patch.object(sys, "frozen", True, create=True)
    mocker.patch.object(sys, "executable", str(executable))
    mocker.patch.dict(os.environ, {"PATH": "/usr/bin"}, clear=True)

    ensure_bundled_ffmpeg_on_path()

    assert os.environ["PATH"] == "/usr/bin"


def test_noop_when_ffmpeg_bin_is_a_file(tmp_path, mocker):
    exe_dir = tmp_path / "MacOS"
    exe_dir.mkdir(parents=True)
    (exe_dir / "ffmpeg-bin").touch()  # a file, not a directory
    executable = exe_dir / "Add Subs to Videos"
    executable.touch()

    mocker.patch.object(sys, "frozen", True, create=True)
    mocker.patch.object(sys, "executable", str(executable))
    mocker.patch.dict(os.environ, {"PATH": "/usr/bin"}, clear=True)

    ensure_bundled_ffmpeg_on_path()

    assert os.environ["PATH"] == "/usr/bin"


def test_idempotent_when_called_twice(tmp_path, mocker):
    exe_dir = tmp_path / "MacOS"
    (exe_dir / "ffmpeg-bin").mkdir(parents=True)
    executable = exe_dir / "Add Subs to Videos"
    executable.touch()

    mocker.patch.object(sys, "frozen", True, create=True)
    mocker.patch.object(sys, "executable", str(executable))
    mocker.patch.dict(os.environ, {"PATH": "/usr/bin"}, clear=True)

    ensure_bundled_ffmpeg_on_path()
    ensure_bundled_ffmpeg_on_path()

    path_entries = os.environ["PATH"].split(os.pathsep)
    assert path_entries.count(str(exe_dir / "ffmpeg-bin")) == 1
    assert path_entries == [str(exe_dir / "ffmpeg-bin"), "/usr/bin"]


def test_resolves_relative_executable_path(tmp_path, mocker, monkeypatch):
    exe_dir = tmp_path / "MacOS"
    (exe_dir / "ffmpeg-bin").mkdir(parents=True)
    executable = exe_dir / "Add Subs to Videos"
    executable.touch()

    monkeypatch.chdir(tmp_path)
    mocker.patch.object(sys, "frozen", True, create=True)
    mocker.patch.object(sys, "executable", os.path.join("MacOS", "Add Subs to Videos"))
    mocker.patch.dict(os.environ, {"PATH": "/usr/bin"}, clear=True)

    ensure_bundled_ffmpeg_on_path()

    path_entries = os.environ["PATH"].split(os.pathsep)
    assert path_entries[0] == str(exe_dir / "ffmpeg-bin")


def test_prepends_snap_usr_bin_when_present(tmp_path, mocker):
    (tmp_path / "usr" / "bin").mkdir(parents=True)

    mocker.patch.object(sys, "frozen", False, create=True)
    mocker.patch.dict(os.environ, {"PATH": "/usr/bin", "SNAP": str(tmp_path)}, clear=True)

    ensure_bundled_ffmpeg_on_path()

    path_entries = os.environ["PATH"].split(os.pathsep)
    assert str(tmp_path / "usr" / "bin") == path_entries[0]
    assert "/usr/bin" in path_entries


def test_noop_when_snap_not_set(mocker):
    mocker.patch.object(sys, "frozen", False, create=True)
    mocker.patch.dict(os.environ, {"PATH": "/usr/bin"}, clear=True)

    ensure_bundled_ffmpeg_on_path()

    assert os.environ["PATH"] == "/usr/bin"


def test_noop_when_snap_usr_bin_missing(tmp_path, mocker):
    mocker.patch.object(sys, "frozen", False, create=True)
    mocker.patch.dict(os.environ, {"PATH": "/usr/bin", "SNAP": str(tmp_path)}, clear=True)

    ensure_bundled_ffmpeg_on_path()

    assert os.environ["PATH"] == "/usr/bin"


def test_idempotent_for_snap_path(tmp_path, mocker):
    (tmp_path / "usr" / "bin").mkdir(parents=True)

    mocker.patch.object(sys, "frozen", False, create=True)
    mocker.patch.dict(os.environ, {"PATH": "/usr/bin", "SNAP": str(tmp_path)}, clear=True)

    ensure_bundled_ffmpeg_on_path()
    ensure_bundled_ffmpeg_on_path()

    path_entries = os.environ["PATH"].split(os.pathsep)
    assert path_entries.count(str(tmp_path / "usr" / "bin")) == 1
    assert path_entries == [str(tmp_path / "usr" / "bin"), "/usr/bin"]
