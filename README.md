### NOTE: This is a vibe coded app. Proceed with caution.

# add_subs_to_videos

You have video files but no subtitles. This tool fixes that.

It crawls a directory recursively, transcribes every video it finds using [whisper.cpp](https://github.com/ggerganov/whisper.cpp), and writes a `.srt` sidecar file next to each one. Already-transcribed files are skipped, so re-running is fast.

## Repo

https://github.com/simnim/add_subs_to_videos

# GUI screenshot

<img src="https://github.com/simnim/add_subs_to_videos/raw/main/assets/screenshots/gui-running.png?raw=true" width="480" alt="GUI – transcription in progress">

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

> `pywhispercpp` compiles a C++ extension at install time (requires CMake — `brew install cmake ffmpeg` on macOS). On Linux with CUDA:
> ```bash
> WHISPER_CUDA=1 pip install "add-subs-to-videos[gui]"
> ```

## Usage

### CLI

```bash
add_subs_to_videos /path/to/videos
add_subs_to_videos /path/to/videos --model large-v3 --language en
add_subs_to_videos /path/to/videos --force   # re-transcribe even if .srt exists
```

`movie.mp4` → `movie.srt`, placed in the same directory. Supports `.mp4`, `.mkv`, `.avi`, `.mov`, `.m4v`, `.webm`, and more.

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
