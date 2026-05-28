# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`add_subs_to_videos` is a Python 3.13 CLI tool that crawls a directory for video files and generates `.srt` subtitle sidecar files using [whisper.cpp](https://github.com/ggerganov/whisper.cpp) (via `pywhispercpp`) for transcription and pyannote.audio for speaker diarization.

Entry points: `crawl-srt` and `add_subs_to_videos` CLIs exposed via `[project.scripts]` → `add_subs_to_videos.cli:main`. Also runnable as `python -m add_subs_to_videos` via `__main__.py`.

## Environment

Uses [uv](https://github.com/astral-sh/uv) for dependency management. Python 3.13 pinned via `.python-version`.

```bash
uv sync                        # install all dependencies (compiles pywhispercpp C++ extension)
uv run add_subs_to_videos --help  # verify entry point works
```

## Running the script

```bash
# Basic usage (transcription only, no speaker labels)
uv run add_subs_to_videos /path/to/videos --model large-v3

# With diarization (speaker labels in output)
HUGGINGFACE_TOKEN=hf_xxx uv run add_subs_to_videos /path/to/videos --model large-v3

# Pin language, override token, force re-run
uv run add_subs_to_videos /path/to/videos --model medium --language en --hf-token hf_xxx --force
```

Output: a `.srt` file placed next to each video (e.g. `movie.mp4` → `movie.srt`). Existing `.srt` files are skipped unless `--force` is passed.

## HuggingFace / pyannote setup

Diarization requires accepting the pyannote model license **before** running:
1. Log in at huggingface.co and visit `huggingface.co/pyannote/speaker-diarization-3.1`
2. Click "Agree and access repository"
3. Generate an access token at `huggingface.co/settings/tokens`
4. Export it: `export HUGGINGFACE_TOKEN=hf_xxx`

## CUDA (Linux/GPU machines)

`pywhispercpp` must be compiled with CUDA support:
```bash
WHISPER_CUDA=1 uv sync
```

The standard PyPI `torch` wheel is CPU-only on Linux. For CUDA, add to `pyproject.toml`:

```toml
[[tool.uv.index]]
name = "pytorch-cuda"
url = "https://download.pytorch.org/whl/cu121"
explicit = true

[tool.uv.sources]
torch = [{ index = "pytorch-cuda", marker = "sys_platform == 'linux'" }]
```

On macOS, Metal (MPS) is auto-detected by both whisper.cpp and pyannote — no extra steps needed.

## Architecture

```
src/add_subs_to_videos/
├── __main__.py   # Enables `python -m add_subs_to_videos`
├── cli.py        # Argument parsing, entry point
├── device.py     # Device detection: CUDA > MPS > CPU
├── files.py      # Recursive video file discovery
├── srt.py        # SRT timestamp formatting and segment serialization
└── transcribe.py # Core pipeline: whisper.cpp transcription + pyannote diarization
```

**Pipeline in `transcribe.py`:**
1. Load `pywhispercpp.model.Model` once per run
2. If `hf_token` provided, load `pyannote.audio.Pipeline` once per run
3. Per video: transcribe with whisper.cpp (word timestamps built-in, no alignment step needed), optionally diarize with pyannote and assign speakers via overlap matching

**Key design decisions:**
- Diarization pipeline is loaded once per directory run, not per video
- Speaker assignment uses a simple max-overlap algorithm (`assign_speakers` in `transcribe.py`)
- `compute_type` is kept in function signatures for API consistency but is not used by whisper.cpp (it self-selects precision)
