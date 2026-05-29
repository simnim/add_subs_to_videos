### NOTE: This is a vibe coded app. Proceed with caution.

# add_subs_to_videos

You have video files but no subtitles. This tool fixes that.

It crawls a directory recursively, transcribes every video it finds using [whisper.cpp](https://github.com/ggerganov/whisper.cpp), and writes a `.srt` sidecar file next to each one. Already-transcribed files are skipped, so re-running is fast and safe.

## Install

```bash
brew install ffmpeg        # macOS
sudo apt install ffmpeg    # Linux
```

```bash
pip install git+https://github.com/simnim/add_subs_to_videos.git
```

> `pywhispercpp` compiles a C++ extension at install time (requires CMake). On macOS, Metal is auto-detected. On Linux with CUDA:
> ```bash
> WHISPER_CUDA=1 pip install git+https://github.com/simnim/add_subs_to_videos.git
> ```

## Usage

```bash
add_subs_to_videos /path/to/videos
add_subs_to_videos /path/to/videos --model large-v3 --language en
add_subs_to_videos /path/to/videos --force   # re-transcribe even if .srt exists
```

`movie.mp4` → `movie.srt`, placed in the same directory. Supports `.mp4`, `.mkv`, `.avi`, `.mov`, `.m4v`, `.webm`, and more.
