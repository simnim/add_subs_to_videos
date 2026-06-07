### NOTE: This is a vibe coded app. Proceed with caution.

# add_subs_to_videos

You have video files but no subtitles. This tool fixes that.

It crawls a directory recursively, transcribes every video it finds using [whisper.cpp](https://github.com/ggerganov/whisper.cpp), and writes a `.srt` sidecar file next to each one. Already-transcribed files are skipped, so re-running is fast and safe.

## Install

**Ubuntu (snap — recommended, no prerequisites):**
```bash
sudo snap install add-subs-to-videos
```

**macOS (.dmg — no prerequisites):**
Download `Add Subs to Videos-<version>.dmg` from [GitHub Releases](https://github.com/simnim/add_subs_to_videos/releases), open it, and drag the app to Applications.

**macOS (CLI via pipx):**
```bash
brew install cmake ffmpeg
pipx install "add-subs-to-videos[gui]"
```
> Metal GPU acceleration is auto-detected on macOS — no extra steps needed.

**Any platform with Python 3.12+:**
```bash
pip install add-subs-to-videos
# or
pipx install add-subs-to-videos
```

> `pywhispercpp` compiles a C++ extension at install time (requires CMake). On Linux with CUDA:
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
