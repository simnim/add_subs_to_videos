### NOTE: This is a vibe coded app. Proceed with caution.

# Add subs to videos:

A Python CLI tool that crawls a directory for video files and generates `.srt` subtitle sidecar files using [WhisperX](https://github.com/m-bain/whisperX) for transcription and pyannote.audio for speaker diarization.

## Motivation

* You're missing subtitles for all those videos you have lying around
* You want to run a simple command to fix all of them in one go

## Install

```bash
uv sync
```

## Usage

```bash
# Basic usage (--model is required)
uv run crawl-srt /path/to/videos --model large-v3

# With diarization (--model is required)
HUGGINGFACE_TOKEN=hf_xxx uv run crawl-srt /path/to/videos --model large-v3

# Pin language, force re-run on existing subtitles
uv run crawl-srt /path/to/videos --model medium --language en --force

# Lower batch size for CPU/MPS (avoids OOM)
uv run crawl-srt ./videos --model small --batch-size 4
```

Each video gets a `.srt` file placed alongside it (e.g. `movie.mp4` → `movie.srt`). Existing `.srt` files are skipped unless `--force` is passed.

## HuggingFace setup

Diarization requires accepting the pyannote model license:

1. Visit `huggingface.co/pyannote/speaker-diarization-3.1` and click "Agree and access repository"
2. Generate a token at `huggingface.co/settings/tokens`
3. Pass it via `HUGGINGFACE_TOKEN=hf_xxx` or `--hf-token hf_xxx`
