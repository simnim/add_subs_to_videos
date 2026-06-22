### NOTE: This is a vibe coded app. Proceed with caution.

# add_subs_to_videos

You have video files but no subtitles. This tool fixes that.

It crawls a directory recursively, transcribes every video it finds using [whisper.cpp](https://github.com/ggerganov/whisper.cpp), and writes a `.srt` sidecar file next to each one. Already-transcribed files are skipped, so re-running is fast.

## Repo

https://github.com/simnim/add_subs_to_videos

## Install

Every option below gives you both the `add_subs_to_videos` CLI command and an
"Add Subs to Videos" desktop GUI.

**Ubuntu (snap — recommended, no prerequisites):**
```bash
sudo snap install add-subs-to-videos
```
Installs the `add-subs-to-videos` CLI plus an "Add Subs to Videos" launcher in your applications menu (`add-subs-to-videos-gui`).

**macOS (.dmg — no prerequisites):**
Download `Add Subs to Videos-<version>.dmg` from [GitHub Releases](https://github.com/simnim/add_subs_to_videos/releases), open it, and drag the app to Applications. The DMG also includes a standalone `add_subs_to_videos` CLI binary and an `Install CLI.command` helper — double-click it to symlink the CLI into `/usr/local/bin` so `add_subs_to_videos --help` works from a terminal.
> Metal GPU acceleration is auto-detected on macOS — no extra steps needed.

**Any platform with Python 3.12+ (via pip/pipx):**
```bash
pip install "add-subs-to-videos[gui]"
# or
pipx install "add-subs-to-videos[gui]"
```
This installs both the `add_subs_to_videos` CLI and the `add-subs-to-videos-gui` GUI entry point. Drop `[gui]` if you only want the CLI.

> `pywhispercpp` compiles a C++ extension at install time (requires CMake — `brew install cmake ffmpeg` on macOS, or on Ubuntu/Debian `sudo apt install cmake ffmpeg`). `ffmpeg`/`ffprobe` are also needed at runtime to decode non-WAV media and show per-file progress. On Linux with an NVIDIA GPU, set `WHISPER_CUDA=1` to compile with CUDA support instead of falling back to CPU:
> ```bash
> WHISPER_CUDA=1 pip install "add-subs-to-videos[gui]" --no-cache-dir
> ```
> Requires the [CUDA Toolkit](https://developer.nvidia.com/cuda-downloads) (`nvcc` on `PATH`) already installed. `--no-cache-dir` forces a rebuild — without it, pip may reuse a cached non-CUDA wheel from a previous install. If you already installed without `WHISPER_CUDA=1`, reinstall with `--force-reinstall --no-cache-dir` to pick up the flag.

## Usage

### CLI

```bash
add_subs_to_videos /path/to/videos
add_subs_to_videos /path/to/videos --model large-v3 --language en
add_subs_to_videos /path/to/videos --force   # re-transcribe even if .srt exists
add_subs_to_videos /path/to/videos --threads 4   # default: all available CPU cores
add_subs_to_videos /path/to/videos --quiet   # only warnings/errors + final summary
add_subs_to_videos /path/to/videos --verbose # debug output, incl. detected language
```

`movie.mp4` → `movie.srt`, placed in the same directory. Supports `.mp4`, `.mkv`, `.avi`, `.mov`, `.m4v`, `.webm`, `.ts`, `.flv`.

Your last-used `directory`, `model`, `language`, and `threads` are remembered in `~/.config/add-subs-to-videos/config.toml`, shared between the CLI and GUI — e.g. pick a folder in the GUI and a later CLI run can omit the directory argument.

### GUI

<img src="https://github.com/simnim/add_subs_to_videos/raw/main/assets/screenshots/gui-running.png?raw=true" width="800" alt="GUI – transcription in progress">

Drag a folder (or single video) onto the window, or click to pick one, then hit Run. Includes handy progress bars for model downloads and live, per-file transcription logs.

- A file table lists every discovered video with a live status (Pending / Processing / Done / Skipped / Failed) and a clickable log icon per row that opens that file's transcript/log output.
- Model dropdown (tiny/base/small/medium/large-v3) shows whether the model is already downloaded, not yet downloaded, or currently downloading.
- Language dropdown offers auto-detect or any of whisper.cpp's supported languages.
- A threads spinbox, a "Force re-run" checkbox, and a "Debug logging" checkbox.
- Overall and per-file progress bars, plus a Cancel button that aborts the current download or in-progress file.
- **Auto re-run:** once a run finishes (and wasn't cancelled), the Run button relabels to a countdown — "Run (auto re-run in M:SS)" — and automatically rescans the folder and re-runs after 10 minutes, so it can be left running unattended to pick up new files as they appear. Clicking Cancel during the countdown stops it.

### Partial subtitles & cancellation

While a file is transcribing, segments are streamed incrementally into a `movie.srt.part` sidecar next to the eventual `movie.srt`, so you can open a growing, valid SRT file mid-run. On success it's atomically renamed to `movie.srt`. If you cancel (or the process is interrupted), the `.part` file is left on disk as-is — it's never deleted, but it's also never resumed: a later run on a file that only has a stray `.part` (no finished `.srt`) re-transcribes it from scratch, overwriting the partial content. Files that already have a completed `.srt` are still skipped unless `--force`/"Force re-run" is set.

## Models

| Model | Speed | Quality |
|-------|-------|---------|
| `tiny` / `base` | Very fast | Lower accuracy |
| `small` / `medium` | Moderate | Good for most content |
| `large-v3` | Slow | Best accuracy |

`medium` is the default. Use `large-v3` when accuracy matters; use `tiny` or `base` for quick drafts on long files.

## Output

Each video gets a `.srt` file in the same directory:

```
movie.mp4  →  movie.srt
```

```
1
00:00:01,240 --> 00:00:04,120
Welcome to the presentation.

2
00:00:04,500 --> 00:00:07,300
Today we'll cover three topics.
```
