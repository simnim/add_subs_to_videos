# CLI Features

The CLI entry point is `add_subs_to_videos` (or `python -m add_subs_to_videos`). It wraps the same `process_directory` pipeline used by the GUI.

## Basic Usage

```bash
add_subs_to_videos /path/to/videos
add_subs_to_videos /path/to/single/video.mp4
```

If a directory has been saved to config previously (e.g. by the GUI), the `directory` argument is optional:

```bash
add_subs_to_videos   # uses saved directory
```

## All Options

| Flag | Default | Description |
|------|---------|-------------|
| `directory` | (saved config) | Video file or root directory to crawl |
| `--model` | `medium` | Whisper model: `tiny`, `base`, `small`, `medium`, `large-v3` |
| `--language` | (auto) | Language code (e.g. `en`, `es`, `fr`). Auto-detects if omitted |
| `--threads N` | all cores | Number of CPU threads for whisper.cpp |
| `--force` | off | Re-transcribe even if `.srt` already exists |
| `--quiet` / `-q` | off | Show only warnings and final summary; suppress progress bars |
| `--verbose` / `-v` | off | Show debug output, including detected language and confidence |

`--quiet` and `--verbose` are mutually exclusive.

## Model Selection

Models trade off speed against accuracy:

| Model | Speed | Accuracy | Best for |
|-------|-------|----------|---------|
| `tiny` | Very fast | Lower | Quick drafts, clear speech |
| `base` | Fast | Lower | Testing |
| `small` | Moderate | Good | Most use cases |
| `medium` | Moderate | Good | Default; good balance |
| `large-v3` | Slow | Best | Highest quality, multilingual |

Models are downloaded on first use and cached locally by `pywhispercpp`. A typical model download happens automatically before transcription begins.

## Output

For each video file, a `.srt` subtitle file is created next to it:

```
movies/
├── documentary.mp4
├── documentary.srt    ← created by add_subs_to_videos
├── lecture.mkv
└── lecture.srt        ← created by add_subs_to_videos
```

Existing `.srt` files are skipped unless `--force` is passed.

## Incremental .srt.part Files

While a file is transcribing, segments are streamed into a `.srt.part` sidecar file:

```
documentary.srt.part   ← live, growing, valid SRT during transcription
```

On completion, the `.part` file is atomically renamed to `.srt`. If the run is interrupted or cancelled, the `.part` file remains but is ignored on the next run — the file will be re-transcribed from scratch.

## Progress Output

By default, the CLI shows:
- A file tree of discovered videos with sizes
- A progress bar per file
- Segment timestamps as they're written: `[00:12 --> 00:18] Hello, welcome...`
- A final summary: files done / skipped / failed

With `--quiet`: only the final summary and any errors.

With `--verbose`: everything above plus detected language and confidence percentage per file.

## Logging Format

Log messages use the format:
```
HH:MM:SS LEVEL message
```

Example:
```
14:32:01 INFO  Processing documentary.mp4
14:32:01 DEBUG Detected language: English (confidence: 98.2%)
14:34:17 INFO  Wrote documentary.srt (127 segments)
```

## Configuration Persistence

The CLI reads from and writes to `~/.config/add-subs-to-videos/config.toml`. Options set via `--model`, `--language`, and `--threads` are persisted automatically, so subsequent runs inherit those values as defaults.

The saved `directory` is used as a fallback when no directory is given on the command line.

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | All files succeeded (or were skipped) |
| `1` | One or more files failed to transcribe |

## Running as a Module

```bash
python -m add_subs_to_videos /path/to/videos --model large-v3
```

This is equivalent to running `add_subs_to_videos` directly and is useful when the entry point isn't on `PATH`.

## Thread Count Tuning

The `--threads` value is passed to whisper.cpp and controls how many CPU cores are used per file. The default uses all available cores. On shared machines or when running other intensive tasks in parallel, limiting threads can reduce contention:

```bash
add_subs_to_videos /videos --threads 4
```

The thread count is automatically capped at the actual core count even if a higher value is passed.
