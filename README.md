### NOTE: This is a vibe coded app. Proceed with caution.

# Problem: 

You don't have subtitles for your favorite video files.

# Solution: add_subs_to_videos

A Python CLI tool that crawls a directory for video files and generates `.srt` subtitle sidecar files using [whisper.cpp](https://github.com/ggerganov/whisper.cpp) (via `pywhispercpp`) for transcription.

## Motivation

* You're missing subtitles for all those videos you have lying around
	* There's many of them in nested directories, too many to think about.
* You want to run a simple command to fix all of them in one go
	* Each file is only transcribed once
	* Even with re-runs we only write files when missing

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
add_subs_to_videos /path/to/videos
add_subs_to_videos /path/to/videos --model large-v3 --language en
add_subs_to_videos /path/to/videos --force   # re-transcribe even if .srt exists
```

Each video gets a `.srt` file placed alongside it (e.g. `movie.mp4` → `movie.srt`). Existing `.srt` files are skipped unless `--force` is passed.
