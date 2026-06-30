# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`add_subs_to_videos` is a Python 3.12+ tool (pinned to 3.13 via `.python-version`) that crawls a directory for video files and generates `.srt` subtitle sidecar files using [whisper.cpp](https://github.com/ggerganov/whisper.cpp) (via `pywhispercpp`) for transcription. It ships both a CLI and an optional PySide6 desktop GUI, both wrapping the same `process_directory` pipeline in `transcribe.py`.

Entry points (`[project.scripts]`):
- `add_subs_to_videos` → `add_subs_to_videos.cli:main` — CLI. Also runnable as `python -m add_subs_to_videos` via `__main__.py`.
- `add-subs-to-videos-gui` → `add_subs_to_videos.gui:main` — desktop GUI (requires the `gui` extra, see below).

## Environment

Uses [uv](https://github.com/astral-sh/uv) for dependency management. Requires Python 3.12+; `.python-version` pins 3.13.

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

# Limit CPU threads (default: all available cores)
uv run add_subs_to_videos /path/to/videos --threads 4

# Quiet (warnings/summary only) or verbose (debug incl. detected language) output
uv run add_subs_to_videos /path/to/videos --quiet
uv run add_subs_to_videos /path/to/videos --verbose
```

Output: a `.srt` file placed next to each video (e.g. `movie.mp4` → `movie.srt`). Existing `.srt` files are skipped unless `--force` is passed. `--quiet`/`-q` and `--verbose`/`-v` are mutually exclusive (`cli.py`'s `build_parser`); quiet sets log level to `WARNING` and disables the progress bar, verbose sets `DEBUG`.

While a file is transcribing, segments stream incrementally into a `movie.srt.part` sidecar next to the eventual `movie.srt`, so the file is a growing, valid SRT mid-run; on success it's atomically renamed to `movie.srt`. A stray `.part` left by a cancelled/interrupted run is never resumed — a later run on that file re-transcribes from scratch and overwrites it. Files with a completed `.srt` are still skipped unless `--force`.

The `directory` argument is optional if a `directory` is saved in config (see Configuration below); otherwise the CLI errors asking for one.

### Running the GUI

```bash
uv run add-subs-to-videos-gui
```

A drag-and-drop window (`gui.py`: `MainWindow`/`DropZone`) for picking a folder or video file, choosing model/language/threads/force options, and watching live overall + per-file progress bars and a transcription log, with a Cancel button. A file table lists every discovered video with a live status (Pending/Processing/Done/Skipped/Failed) and a clickable log icon per row (icon appears after the first log line arrives) that opens that file's transcript/log output. Other controls: a threads spinbox, a "Force re-run" checkbox, a "Debug logging" checkbox, an "Auto re-run" toggle checkbox (persisted in config), and a Clear button to deselect the current folder.

The model dropdown shows a ✓ icon for already-cached models and a ↓ icon for models not yet downloaded. When a run starts with an uncached model, the UI shows a download progress bar ("Downloading model 'name'… X.XX GB / Y.YY GB") driven by the `on_model_progress` callback in `process_directory`.

If a `directory` is saved in config, the file table auto-populates on app launch (no Run needed to see the file list). The drop zone supports keyboard navigation: Tab cycles focus to it, Enter/Space opens the folder picker.

It runs `process_directory` on a background `QThread` (`_WorkerThread`), wiring its `on_progress`/`on_segment`/`on_file_progress`/`on_model_progress` callbacks to Qt signals and forwarding `logging`/stdout output to the on-screen log via a custom `logging.Handler`.

**Auto re-run:** when the "Auto re-run" checkbox is enabled (default on, persisted), once a run finishes (and wasn't cancelled) the Run button relabels to a countdown — "Run (auto re-run in M:SS)" — and automatically rescans the folder and re-runs after 10 minutes, so it can be left running unattended to pick up new files as they appear. Clicking Cancel during the countdown stops it.

## Configuration

`config.py` persists user preferences (`model`, `language`, `directory`, `threads`, `auto_rerun`) as TOML at `$XDG_CONFIG_HOME/add-subs-to-videos/config.toml` (defaults to `~/.config/...`). Both the CLI (`load_config()` feeds `argparse` defaults via `set_defaults`) and the GUI (loaded on startup; saved on folder selection and window close) read and write this same file — so, e.g., picking a folder in the GUI lets you omit `directory` on a subsequent CLI run, and vice versa.

## Testing

```bash
uv sync --group dev --extra gui       # install dev + GUI deps (pytest, pytest-qt, etc.)
uv run pytest tests/ -m "not integration"   # fast unit tests
uv run pytest tests/ -m integration         # slow end-to-end tests against bundled audio in tests/demo-audio/
```

`tests/` has one test file per module (`test_cli_main.py`, `test_config.py`, `test_crawl_srt.py`, `test_gui.py`, `test_integration.py`, `test_main_entrypoint.py`, `test_runtime_paths.py`) plus `conftest.py`. GUI tests use `pytest-qt`; integration tests use `pytest-forked` on Linux CI to isolate native crashes (whisper.cpp segfaults shouldn't take down the whole test run).

No lint/type-check tooling is configured (no ruff/mypy/pre-commit) — pytest is the only check to run.

## CI

`.github/workflows/ci.yml` runs on every push/PR to `main`: matrix `[ubuntu-latest, macos-latest]`, installs system deps (ffmpeg/cmake/Qt libs on Linux via `apt`, ffmpeg/cmake on macOS via `brew`), then runs the same two pytest commands as above. This is the gate to satisfy before pushing.

## Publishing

Releases are triggered by creating a GitHub Release. `scripts/release.sh` is the helper script for cutting one. Three workflows fire automatically:

- **`.github/workflows/publish.yml`** — builds a wheel with `uv build` and uploads to PyPI using the `PYPI_TOKEN` secret (or OIDC trusted publishing with `--trusted-publishing always`)
- **`.github/workflows/snap.yml`** — builds the snap with `snapcore/action-build` and publishes to the Snap Store using the `SNAPCRAFT_STORE_CREDENTIALS` secret
- **`.github/workflows/mac-release.yml`** — builds the macOS `.dmg` via `packaging/mac/build_mac.sh` and uploads it to the GitHub release

Snap packaging lives in `snap/snapcraft.yaml`. The `python` plugin compiles `pywhispercpp` (C++ extension) during the snap build and bundles `ffmpeg` via `stage-packages`, so the snap is fully self-contained.

### macOS .dmg

`packaging/mac/build_mac.sh` builds both the GUI `.app` and a CLI bundle with PyInstaller (`packaging/mac/add_subs_to_videos.spec`), then runs `packaging/mac/bundle_ffmpeg.sh` against each. That script copies Homebrew's `ffmpeg`/`ffprobe` plus their dylib dependencies (resolved via `dylibbundler`) into an `ffmpeg-bin/` folder next to each bundle's executable, so the `.dmg` is fully self-contained — no `brew install ffmpeg` needed by end users. At startup, `runtime_paths.ensure_bundled_ffmpeg_on_path()` (called from both `cli.py:main()` and `gui.py:main()`) detects when running from a PyInstaller bundle and prepends that `ffmpeg-bin/` directory to `PATH`, which is how both `_probe_duration()`'s `ffprobe` call and `pywhispercpp`'s internal `ffmpeg` call (used to decode non-WAV media) find the binaries. Building requires `brew install ffmpeg cmake librsvg create-dmg dylibbundler`.

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
├── __main__.py     # Enables `python -m add_subs_to_videos`
├── cli.py          # Argument parsing, entry point
├── config.py       # Shared TOML settings persistence (~/.config/add-subs-to-videos/config.toml)
├── files.py        # Recursive video file discovery (.mp4 .mkv .avi .mov .m4v .webm .ts .flv)
├── gui.py          # PySide6 desktop app (drag-and-drop, progress, log) wrapping process_directory
├── runtime_paths.py # Locates bundled ffmpeg when running from a PyInstaller bundle
├── srt.py          # SRT timestamp formatting and segment serialization
└── transcribe.py   # Core pipeline: whisper.cpp transcription

tests/
├── conftest.py
├── demo-audio/            # Bundled audio fixture for integration tests
├── test_cli_main.py
├── test_config.py
├── test_crawl_srt.py
├── test_gui.py
├── test_integration.py
├── test_main_entrypoint.py
└── test_runtime_paths.py

docs/                      # User-facing documentation (CLI, GUI, install, recipes, packaging, troubleshooting)
```

`assets/icon.svg` provides the GUI's app icon — located at runtime by `gui.py`'s `_dev_icon_path()` and bundled via `snap/snapcraft.yaml`. `assets/add-subs-to-videos-gui.desktop` provides the Linux desktop entry for the GUI launcher.

**Pipeline in `transcribe.py`:**
1. Optionally download the model (with HTTP Range resume) reporting bytes via `on_model_progress(downloaded, total)`
2. Load `pywhispercpp.model.Model` once per run
3. Per video: transcribe with whisper.cpp, convert raw segments to dicts, serialize to SRT; progress reported via `ProgressEvent` dataclass (fields: `stage`, `index`, `total`, `video`, `done`, `skipped`, `failed`, `elapsed`)

`process_directory()` accepts `cancel: threading.Event` for cooperative cancellation (checked between files and during model download). Helper functions `is_model_downloaded(model_name)` and `model_file_path(model_name)` are public utilities used by the GUI to show cached/uncached icons without starting a run.

**Key design decisions:**
- Model is loaded once per directory run, not per video
- whisper.cpp self-selects precision; no compute_type needed
- The GUI never calls the transcription pipeline directly from the UI thread — `_WorkerThread` in `gui.py` runs `process_directory` on a `QThread` and relays progress/log/cancellation across the thread boundary via Qt signals
