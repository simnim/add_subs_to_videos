# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`add_subs_to_videos` is a Python 3.13 CLI tool that crawls a directory for video files and generates `.srt` subtitle sidecar files using [whisper.cpp](https://github.com/ggerganov/whisper.cpp) (via `pywhispercpp`) for transcription.

Entry point: `add_subs_to_videos` CLI exposed via `[project.scripts]` → `add_subs_to_videos.cli:main`. Also runnable as `python -m add_subs_to_videos` via `__main__.py`.

## Environment

Uses [uv](https://github.com/astral-sh/uv) for dependency management. Python 3.13 pinned via `.python-version`.

```bash
uv sync                        # install all dependencies (compiles pywhispercpp C++ extension)
uv run add_subs_to_videos --help  # verify entry point works
```

## Running the script

```bash
# Basic usage
uv run add_subs_to_videos /path/to/videos --model large-v3

# Pin language, force re-run
uv run add_subs_to_videos /path/to/videos --model medium --language en --force
```

Output: a `.srt` file placed next to each video (e.g. `movie.mp4` → `movie.srt`). Existing `.srt` files are skipped unless `--force` is passed.

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
├── files.py      # Recursive video file discovery
├── srt.py        # SRT timestamp formatting and segment serialization
└── transcribe.py # Core pipeline: whisper.cpp transcription
```

**Pipeline in `transcribe.py`:**
1. Load `pywhispercpp.model.Model` once per run
2. Per video: transcribe with whisper.cpp, convert raw segments to dicts, serialize to SRT

**Key design decisions:**
- Model is loaded once per directory run, not per video
- whisper.cpp self-selects precision; no compute_type needed
