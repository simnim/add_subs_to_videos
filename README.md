### NOTE: This is a vibe coded app. Proceed with caution.

# add_subs_to_videos

You have video files but no subtitles. This tool fixes that.

It crawls a directory recursively, transcribes every video it finds using [whisper.cpp](https://github.com/ggerganov/whisper.cpp), and writes a `.srt` sidecar file next to each one. Already-transcribed files are skipped, so re-running is fast and safe.

## Install

**Ubuntu (snap — recommended, no prerequisites):**
```bash
sudo snap install add-subs-to-videos
```

**Any platform with Python 3.12+:**
```bash
pip install add-subs-to-videos
# or
pipx install add-subs-to-videos
```

> `pywhispercpp` compiles a C++ extension at install time (requires CMake). On macOS, Metal is auto-detected. On Linux with CUDA:
> ```bash
> WHISPER_CUDA=1 pip install add-subs-to-videos
> ```

## Usage

```bash
add_subs_to_videos /path/to/videos
add_subs_to_videos /path/to/videos --model large-v3 --language en
add_subs_to_videos /path/to/videos --force   # re-transcribe even if .srt exists
```

`movie.mp4` → `movie.srt`, placed in the same directory. Supports `.mp4`, `.mkv`, `.avi`, `.mov`, `.m4v`, `.webm`, and more.
