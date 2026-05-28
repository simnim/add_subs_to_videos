### NOTE: This is a vibe coded app. Proceed with caution.

# Add subs to videos:

A Python CLI tool that crawls a directory for video files and generates `.srt` subtitle sidecar files using [whisper.cpp](https://github.com/ggerganov/whisper.cpp) for transcription and pyannote.audio for speaker diarization.

## Motivation

* You're missing subtitles for all those videos you have lying around
* You want to run a simple command to fix all of them in one go

## Install

**With pip:**
```bash
pip install git+https://github.com/simnim/add_subs_to_videos.git
```

`pywhispercpp` compiles a C++ extension at install time and requires CMake. On macOS, Metal acceleration is auto-detected. On Linux with CUDA, set `WHISPER_CUDA=1` before installing:
```bash
WHISPER_CUDA=1 pip install git+https://github.com/simnim/add_subs_to_videos.git
```

## Usage

```bash
# Basic usage
add_subs_to_videos /path/to/videos

# With diarization (speaker labels in output)
HUGGINGFACE_TOKEN=hf_xxx add_subs_to_videos /path/to/videos --model large-v3
```

Each video gets a `.srt` file placed alongside it (e.g. `movie.mp4` → `movie.srt`). Existing `.srt` files are skipped unless `--force` is passed.

## HuggingFace setup (optional)

Diarization (speaker labels) requires accepting the pyannote model license:

1. Visit `huggingface.co/pyannote/speaker-diarization-3.1` and click "Agree and access repository"
2. Generate a token at `huggingface.co/settings/tokens`
3. Pass it via `HUGGINGFACE_TOKEN=hf_xxx` or `--hf-token hf_xxx`

Diarization is optional — omit the token to get transcription-only output without speaker labels.
