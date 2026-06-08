# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`add_subs_to_videos` is a Python 3.13 tool that crawls a directory for video files and generates `.srt` subtitle sidecar files using [whisper.cpp](https://github.com/ggerganov/whisper.cpp) (via `pywhispercpp`) for transcription. It ships both a CLI and an optional PySide6 desktop GUI, both wrapping the same `process_directory` pipeline in `transcribe.py`.

Entry points (`[project.scripts]`):
- `add_subs_to_videos` → `add_subs_to_videos.cli:main` — CLI. Also runnable as `python -m add_subs_to_videos` via `__main__.py`.
- `add-subs-to-videos-gui` → `add_subs_to_videos.gui:main` — desktop GUI (requires the `gui` extra, see below).

## Environment

Uses [uv](https://github.com/astral-sh/uv) for dependency management. Python 3.13 pinned via `.python-version`.

```bash
uv sync                        # install all dependencies (compiles pywhispercpp C++ extension)
uv sync --extra gui            # also install GUI dependencies (PySide6)
uv run add_subs_to_videos --help  # verify entry point works
```

## Running the script

```bash
# Basic usage
uv run add_subs_to_videos /path/to/videos --model large-v3

# Pin language, force re-run
uv run add_subs_to_videos /path/to/videos --model medium --language en --force

# Quiet (warnings/summary only) or verbose (debug incl. detected language) output
uv run add_subs_to_videos /path/to/videos --quiet
uv run add_subs_to_videos /path/to/videos --verbose
```

Output: a `.srt` file placed next to each video (e.g. `movie.mp4` → `movie.srt`). Existing `.srt` files are skipped unless `--force` is passed. `--quiet`/`-q` and `--verbose`/`-v` are mutually exclusive (`cli.py`'s `build_parser`); quiet sets log level to `WARNING` and disables the progress bar, verbose sets `DEBUG`.

The `directory` argument is optional if a `directory` is saved in config (see Configuration below); otherwise the CLI errors asking for one.

### Running the GUI

```bash
uv run add-subs-to-videos-gui
```

A drag-and-drop window (`gui.py`: `MainWindow`/`DropZone`) for picking a folder or video file, choosing model/language/force options, and watching live overall + per-file progress bars and a transcription log, with a Cancel button. It runs `process_directory` on a background `QThread` (`_WorkerThread`), wiring its `on_progress`/`on_segment`/`on_file_progress` callbacks to Qt signals and forwarding `logging`/stdout output to the on-screen log via a custom `logging.Handler`.

## Configuration

`config.py` persists user preferences (`model`, `language`, `directory`) as TOML at `$XDG_CONFIG_HOME/add-subs-to-videos/config.toml` (defaults to `~/.config/...`). Both the CLI (`load_config()` feeds `argparse` defaults via `set_defaults`) and the GUI (loaded on startup; saved on folder selection and window close) read and write this same file — so, e.g., picking a folder in the GUI lets you omit `directory` on a subsequent CLI run, and vice versa.

## Publishing

Releases are triggered by creating a GitHub Release. Two workflows fire automatically:

- **`.github/workflows/publish.yml`** — builds a wheel with `uv build` and uploads to PyPI using the `PYPI_TOKEN` secret (or OIDC trusted publishing with `--trusted-publishing always`)
- **`.github/workflows/snap.yml`** — builds the snap with `snapcore/action-build` and publishes to the Snap Store using the `SNAPCRAFT_STORE_CREDENTIALS` secret

Snap packaging lives in `snap/snapcraft.yaml`. The `python` plugin compiles `pywhispercpp` (C++ extension) during the snap build and bundles `ffmpeg` via `stage-packages`, so the snap is fully self-contained.

One-time setup before first release:
```bash
snap install snapcraft --classic
snapcraft login
snapcraft register add-subs-to-videos
snapcraft export-login ...   # paste output into SNAPCRAFT_STORE_CREDENTIALS secret
```

## CUDA (Linux/GPU machines)

`pywhispercpp` must be compiled with CUDA support:
```bash
WHISPER_CUDA=1 uv sync
```

On macOS, Metal is auto-detected by whisper.cpp — no extra steps needed.

## Architecture

```
src/add_subs_to_videos/
├── __main__.py   # Enables `python -m add_subs_to_videos`
├── cli.py        # Argument parsing, entry point
├── config.py     # Shared TOML settings persistence (~/.config/add-subs-to-videos/config.toml)
├── files.py      # Recursive video file discovery
├── gui.py        # PySide6 desktop app (drag-and-drop, progress, log) wrapping process_directory
├── srt.py        # SRT timestamp formatting and segment serialization
└── transcribe.py # Core pipeline: whisper.cpp transcription
```

`assets/icon.svg` provides the GUI's app icon — located at runtime by `gui.py`'s `_dev_icon_path()` and bundled via `snap/snapcraft.yaml`. `assets/add-subs-to-videos-gui.desktop` provides the Linux desktop entry for the GUI launcher.

**Pipeline in `transcribe.py`:**
1. Load `pywhispercpp.model.Model` once per run
2. Per video: transcribe with whisper.cpp, convert raw segments to dicts, serialize to SRT

**Key design decisions:**
- Model is loaded once per directory run, not per video
- whisper.cpp self-selects precision; no compute_type needed
- The GUI never calls the transcription pipeline directly from the UI thread — `_WorkerThread` in `gui.py` runs `process_directory` on a `QThread` and relays progress/log/cancellation across the thread boundary via Qt signals
