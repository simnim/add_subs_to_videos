# How-To Guide

Common tasks and step-by-step instructions for `add_subs_to_videos`.

## Transcribe a Single Video

```bash
add_subs_to_videos /path/to/video.mp4
```

Output: `/path/to/video.srt` placed next to the source file.

## Transcribe All Videos in a Folder

```bash
add_subs_to_videos /path/to/videos/
```

Recursively finds all `.mp4`, `.mkv`, `.avi`, `.mov`, `.m4v`, `.webm`, `.ts`, and `.flv` files and transcribes each one.

## Re-Transcribe Files That Already Have Subtitles

By default, files with an existing `.srt` are skipped. Use `--force` to override:

```bash
add_subs_to_videos /videos --force
```

## Use a Specific Model

```bash
add_subs_to_videos /videos --model large-v3   # best quality, slower
add_subs_to_videos /videos --model tiny       # fastest, lower quality
```

The model is downloaded automatically on first use. Downloaded models are cached by `pywhispercpp` and reused on subsequent runs.

## Pin the Language

If you know all the videos are in a specific language, pinning it speeds things up slightly and avoids rare language misdetections:

```bash
add_subs_to_videos /videos --language en
add_subs_to_videos /videos --language ja
add_subs_to_videos /videos --language fr
```

Use the two-letter ISO 639-1 code. To reset back to auto-detect, just omit `--language`.

## Limit CPU Usage

```bash
add_subs_to_videos /videos --threads 2
```

By default, all available CPU cores are used. Limiting threads is useful on shared machines or when running other work in parallel.

## Run Quietly (Cron / Automation)

```bash
add_subs_to_videos /videos --quiet
```

`--quiet` suppresses progress bars and per-file output. Only warnings and the final summary are printed. Exit code is `0` on full success, `1` if any file failed.

## See Detected Language and Confidence

```bash
add_subs_to_videos /videos --verbose
```

When language auto-detection is on, `--verbose` logs the detected language and confidence percentage for each file:

```
14:32:01 DEBUG Detected language: Spanish (confidence: 94.7%)
```

## Leave the GUI Running to Pick Up New Files

1. Open the GUI and select your videos folder
2. Check **Auto re-run**
3. Click **Run**

After each completed run, the app counts down 10 minutes and automatically rescans and retranscribes new files. This is useful for a "watch folder" setup where new videos arrive over time.

## Check Whether a Model Is Downloaded (GUI)

In the model dropdown, models that are already cached show a **✓** checkmark next to their name. Models that need downloading show a **↓** arrow.

## Open a File's Transcript Mid-Run

During a run in the GUI, click the 📋 icon next to any file in the file table. A dialog opens showing the segments that have been transcribed so far, updating live as more arrive.

## Switch Models Between Runs

The GUI saves the selected model to config. Change the model in the dropdown before clicking Run and the new model will be used. If the new model isn't downloaded yet, the download starts automatically before transcription begins.

## Access Previously Used Settings from the CLI

Settings saved by the GUI (model, language, directory, threads) are available to the CLI automatically:

```bash
add_subs_to_videos   # uses saved directory, model, language, and threads
```

To override a saved value just for one run, pass the flag explicitly:

```bash
add_subs_to_videos --model tiny   # override model, keep other saved values
```

## Enable CUDA on Linux

If you have an NVIDIA GPU and want hardware-accelerated transcription:

```bash
WHISPER_CUDA=1 pip install add_subs_to_videos
```

This triggers a CUDA-enabled build of whisper.cpp. After installation, transcription automatically uses the GPU.

## Recover from a Partial Run

If a run was interrupted, `.srt.part` files may remain next to videos:

```bash
find /videos -name "*.srt.part"
```

These are safe to delete. On the next run, those videos will be re-transcribed from scratch. The `.srt.part` files are not used for resuming — they're just leftover working files.

## Install the CLI on macOS (from the DMG)

1. Mount the `.dmg`
2. Drag **Add Subs to Videos.app** to `/Applications`
3. Double-click **Install CLI.command** in the DMG

The CLI will be symlinked to `/usr/local/bin/add_subs_to_videos` and available from any terminal.
