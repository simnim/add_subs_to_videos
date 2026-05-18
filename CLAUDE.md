# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`add_subs_to_videos` is a Python 3.13 CLI tool that crawls a directory for video files and generates `.srt` subtitle sidecar files using [WhisperX](https://github.com/m-bain/whisperX) (transcription + word alignment) and pyannote.audio (speaker diarization).

Main script: `crawl_srt.py` — entry point exposed as `crawl-srt` via `[project.scripts]`.

## Environment

Uses [uv](https://github.com/astral-sh/uv) for dependency management. Python 3.13 pinned via `.python-version`.

```bash
uv sync                  # install all dependencies
uv run crawl-srt --help  # verify entry point works
```

## Running the script

```bash
# Basic usage (--model is required)
HUGGINGFACE_TOKEN=hf_xxx uv run crawl-srt /path/to/videos --model large-v3

# Pin language, override token, force re-run
uv run crawl-srt /path/to/videos --model medium --language en --hf-token hf_xxx --force

# Lower batch size for CPU/MPS (avoids OOM)
uv run crawl-srt ./videos --model small --batch-size 4
```

Output: a `.srt` file placed next to each video (e.g. `movie.mp4` → `movie.srt`). Existing `.srt` files are skipped unless `--force` is passed.

## HuggingFace / pyannote setup

Diarization requires accepting the pyannote model license **before** running:
1. Log in at huggingface.co and visit `huggingface.co/pyannote/speaker-diarization-3.1`
2. Click "Agree and access repository"
3. Generate an access token at `huggingface.co/settings/tokens`
4. Export it: `export HUGGINGFACE_TOKEN=hf_xxx`

## CUDA (Linux/GPU machines)

The standard PyPI `torch` wheel is CPU-only on Linux. For CUDA, add to `pyproject.toml`:

```toml
[[tool.uv.index]]
name = "pytorch-cuda"
url = "https://download.pytorch.org/whl/cu121"
explicit = true

[tool.uv.sources]
torch = [{ index = "pytorch-cuda", marker = "sys_platform == 'linux'" }]
```

On macOS, the PyPI wheel includes MPS support — no extra index needed.
