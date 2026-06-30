# Troubleshooting

Solutions to common problems.

## Installation

### `pywhispercpp` fails to build during install

`pywhispercpp` compiles whisper.cpp from source. A missing C++ compiler or CMake is the most common cause.

**macOS:**
```bash
xcode-select --install      # install Clang + CMake from Apple
brew install cmake          # or install CMake via Homebrew
```

**Ubuntu/Debian:**
```bash
sudo apt install build-essential cmake
```

Then retry:
```bash
pip install add_subs_to_videos
# or
uv sync
```

### GUI fails to launch: `ImportError: No module named 'PySide6'`

The GUI extra wasn't installed:

```bash
pip install "add_subs_to_videos[gui]"
# or
uv sync --extra gui
```

---

## Transcription

### "ffprobe not found" or no per-file progress bar

ffmpeg (which includes ffprobe) isn't on `PATH`. Duration probing is optional — transcription still works without it — but per-file progress won't be shown.

Install ffmpeg:
- macOS: `brew install ffmpeg`
- Ubuntu: `sudo apt install ffmpeg`
- Windows: Download from https://ffmpeg.org and add to PATH

### Transcription fails with a cryptic C-level error

Run with `--verbose` to capture more detail:

```bash
add_subs_to_videos /videos --verbose
```

Common causes:
- **Corrupted video file:** Try playing the file in VLC to confirm it's intact
- **Unsupported codec:** Check the output for an ffmpeg error about codec support
- **Out of memory:** Large models (`large-v3`) require several GB of RAM. Try `--model medium` or `--model small`

### Output SRT has garbled text or wrong language

The model auto-detected the wrong language. Pin it explicitly:

```bash
add_subs_to_videos /videos --language en
```

Use `--verbose` to see what language was detected and with what confidence.

### Transcription is extremely slow

- **Use a smaller model:** `--model small` or `--model base` is much faster than `large-v3`
- **Check GPU acceleration:** On macOS, Metal should auto-activate. On Linux, you need to rebuild with `WHISPER_CUDA=1`
- **Check thread count:** The default uses all cores. If something else is competing for CPU, try reducing: `--threads 4`

### `.srt.part` files left over after a cancelled run

These are safe to delete:

```bash
find /videos -name "*.srt.part" -delete
```

On the next run, those videos will be re-transcribed from scratch.

### A file keeps being skipped even with `--force`

`--force` overrides the skip-if-exists check, but if the file errors during transcription, it won't produce a `.srt`. Check the log for error messages:

```bash
add_subs_to_videos /videos --force --verbose
```

---

## Model Downloads

### Model download is slow or hangs

The model download can be resumed. If it hangs:
1. Press Ctrl-C to cancel
2. Re-run the same command — the download will resume from where it left off

### "No space left on device" during model download

Models are cached in the `pywhispercpp` data directory (usually `~/.cache/huggingface/hub/` or similar). Check disk space:

```bash
df -h ~
```

Remove unused cached models to free space.

### Model download succeeds but transcription immediately fails

The partial `.part` file from a previous failed download may still be present. Find and delete it:

```bash
find ~/.cache -name "*.ggml.part" -delete 2>/dev/null
find ~/Library/Application\ Support -name "*.ggml.part" -delete 2>/dev/null  # macOS
```

---

## Configuration

### Saved settings aren't being used

The config file is at `~/.config/add-subs-to-videos/config.toml`. Verify it exists and contains the expected values:

```bash
cat ~/.config/add-subs-to-videos/config.toml
```

If the file is malformed TOML, `config.py` silently ignores it and uses defaults. Delete it to reset:

```bash
rm ~/.config/add-subs-to-videos/config.toml
```

### CLI ignores saved `directory` from config

The CLI falls back to the saved directory only when no `directory` argument is given. If you explicitly pass a path on the command line, that overrides the saved value.

---

## Snap (Linux)

### Snap can't access external drives

The snap requires the `removable-media` interface to be connected:

```bash
sudo snap connect add-subs-to-videos:removable-media
```

### Snap can't download models (network error)

Check that the `network` interface is connected:

```bash
snap connections add-subs-to-videos
```

The `network` plug should be connected automatically, but can be checked and reconnected:

```bash
sudo snap connect add-subs-to-videos:network
```

---

## macOS DMG

### "Add Subs to Videos is damaged and can't be opened"

macOS Gatekeeper quarantines unsigned apps. To bypass:

```bash
xattr -cr "/Applications/Add Subs to Videos.app"
```

Then try opening again.

### CLI not found after running "Install CLI.command"

The install script symlinks to `/usr/local/bin`. Check if this is on your PATH:

```bash
echo $PATH
which add_subs_to_videos
```

If `/usr/local/bin` isn't in PATH, add it to your shell profile (`~/.zshrc` or `~/.bash_profile`):

```bash
export PATH="/usr/local/bin:$PATH"
```

---

## GUI

### GUI window is blank or very small on Linux

Ensure Qt platform plugins are installed. On Ubuntu:

```bash
sudo apt install libqt6gui6 libqt6widgets6 libqt6core6
```

If installing from pip, you may also need:

```bash
sudo apt install libxcb-cursor0
```

### Auto re-run doesn't seem to pick up new files

The auto re-run rescans the folder before each run, so new files are picked up. If files aren't appearing:
- Confirm the files have one of the supported extensions (`.mp4`, `.mkv`, `.avi`, `.mov`, `.m4v`, `.webm`, `.ts`, `.flv`)
- Confirm the files don't already have a corresponding `.srt` (use **Force re-run** if you want to re-process them)

### Log dialog doesn't update live during transcription

The per-file log dialog shows output only for the file being transcribed. If you opened the dialog for a file that hasn't started yet, it will be empty until that file begins processing.
