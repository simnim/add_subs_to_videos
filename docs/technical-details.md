# Technical Details

Internal architecture, design decisions, and implementation specifics for contributors and advanced users.

## Pipeline Overview

```
process_directory()
├── find_videos(root)               # Recursive scan; sorted alphabetically
├── _download_model()               # If not cached; resumes partial downloads
└── for each video:
    ├── skip if .srt exists         # Unless force=True
    ├── _probe_duration()           # ffprobe for progress tracking
    ├── transcribe_video()
    │   ├── Model.transcribe()      # pywhispercpp → whisper.cpp
    │   ├── stream to .srt.part     # Atomic: written per-segment
    │   └── on_segment / on_file_progress callbacks
    └── rename .srt.part → .srt    # Atomic rename on success
```

## Atomic Write Pattern

Every `.srt` file is written atomically:

1. Segments stream into `video.srt.part` during transcription
2. On success: `video.srt.part` is renamed to `video.srt` — one atomic `os.rename()` call
3. On failure/cancellation: the `.part` file remains, but is ignored on the next run

This ensures that a `.srt` file is either complete and valid, or absent. There is no state where a partial `.srt` exists and is used as input.

## Model Download with Resumption

`_download_model()` in `transcribe.py` downloads ggml model files with HTTP Range request support:

- Downloads to `model_name.ggml.part`
- If the `.part` file already exists, sends `Range: bytes=<size>-` to resume
- Throttles progress callbacks to at most one update per 100ms to avoid flooding GUI signals
- Renames to final filename atomically on completion
- Supports cancellation via `threading.Event`

## Cancellation Architecture

Cancellation is cooperative throughout. The cancel token is a `threading.Event`:

```python
cancel = threading.Event()
cancel.set()  # request cancellation
```

Checked at two levels:
- **Between files:** `process_directory` checks `cancel.is_set()` before starting each file
- **Within a file:** `transcribe_video` checks after each segment callback; raises `_Cancelled` to abort mid-file

The `.srt.part` file for a cancelled file is left on disk but will be overwritten on the next run.

## Progress Callback System

`process_directory` accepts four callback functions:

| Callback | Signature | When called |
|----------|-----------|-------------|
| `on_progress` | `(ProgressEvent)` | Start, done, skip, fail, summary for each file |
| `on_segment` | `(str)` | Each transcribed segment: `[MM:SS --> MM:SS] text` |
| `on_file_progress` | `(float)` | 0.0–1.0 within current file (uses ffprobe duration) |
| `on_model_progress` | `(float)` | 0.0–1.0 during model download |

`ProgressEvent` is a dataclass:

```python
@dataclass
class ProgressEvent:
    stage: str         # "start" | "done" | "skip" | "fail" | "summary"
    index: int         # 1-based, including current file
    total: int
    video: Path
    done: int
    skipped: int
    failed: int
    elapsed: float | None  # only on "summary"
```

## SRT Format

The SRT format written by `srt.py`:

```
1
00:00:01,240 --> 00:00:04,120
Welcome to the presentation.

2
00:00:04,350 --> 00:00:07,890
Today we'll be discussing...
```

Key details:
- Timestamps use comma as decimal separator (standard SRT)
- Milliseconds are always 3 digits
- Entries are separated by a blank line
- Empty segments (whitespace-only text) are dropped
- Leading/trailing whitespace stripped from segment text

## Video Discovery

`files.py` defines the supported extensions:

```python
VIDEO_EXTENSIONS = frozenset({
    ".mp4", ".mkv", ".avi", ".mov", ".m4v", ".webm", ".ts", ".flv"
})
```

`find_videos(root)` behavior:
- **Directory:** Walks recursively via `Path.rglob("*")`, filters by extension, sorts alphabetically
- **Single file:** Validates extension and returns `[path]`; exits with error if unsupported
- **Nonexistent path:** Exits with error immediately

## Duration Probing

`_probe_duration(path)` calls ffprobe to get media duration for progress calculation:

```bash
ffprobe -v quiet -print_format json -show_streams <path>
```

Parses `streams[0].duration` from the JSON output. Returns `None` if ffprobe isn't available or the format isn't recognized — in that case, `on_file_progress` callbacks simply aren't emitted for that file.

## Native Output Capture

whisper.cpp prints directly to C-level stdout/stderr during transcription. The `_capture_native_output()` context manager in `transcribe.py` redirects these via `os.dup2()`:

```python
with _capture_native_output("whisper"):
    model.transcribe(audio_path, ...)
```

The captured output is fed into Python's `logging` system so it appears in the GUI transcript log alongside Python log messages.

## Configuration File Format

Stored at `$XDG_CONFIG_HOME/add-subs-to-videos/config.toml` (default: `~/.config/add-subs-to-videos/config.toml`):

```toml
model = "large-v3"
language = "en"
directory = "/path/to/videos"
threads = 8
auto_rerun = true
```

`config.py` manages reading and writing this file. Only the five whitelisted keys are ever read; unknown keys in the file are ignored. `save_config(updates)` merges the update dict with the existing file, dropping any keys with `None` or empty-string values.

## GUI Threading Model

The GUI uses two background threads:

**`_FileScanThread`** (lightweight):
- Runs `find_videos()` asynchronously after folder selection
- Emits `files_ready(list[Path])` signal
- Populates the file table without blocking the UI

**`_WorkerThread`** (heavy):
- Runs `process_directory()` for the full transcription run
- Captures Python `logging` records and stdout via a custom `logging.Handler`
- Routes everything to the UI via Qt signals
- Holds a `threading.Event` cancel token exposed via `cancel()` method

All UI updates happen in the main thread via Qt's signal/slot mechanism. No direct widget access from background threads.

## GUI Progress Bar Scale

The overall progress bar uses a range of `0` to `total_files * 1000`. Progress within a file is tracked as `file_index * 1000 + file_fraction * 1000`. This gives smooth sub-file progress on the overall bar without floating-point QProgressBar values.

## PyInstaller Entry Points

The macOS DMG uses thin launcher scripts instead of pointing PyInstaller directly at module paths:

```python
# gui_launcher.py
from add_subs_to_videos.gui import main
main()
```

This is necessary because PyInstaller needs a concrete script file as its entry point, not a dotted module path.

## Error Description on Failure

When `transcribe_video()` raises an exception, `_describe_transcription_error()` re-runs ffmpeg on the problematic file to capture the actual error output. This surfaces encoding issues, corrupted files, or unsupported codecs as human-readable messages in the log rather than raw Python exceptions.

## Snap PATH Injection

When running inside a snap, `$SNAP` is set to the snap's mount directory. `runtime_paths.py` prepends `$SNAP/usr/bin` to `PATH` at startup so that `ffprobe` and whisper.cpp's internal `ffmpeg` resolve to the snap-bundled binaries rather than requiring system installations.

## GPU Acceleration

| Platform | Mechanism | How to enable |
|----------|-----------|---------------|
| macOS | Metal (via whisper.cpp) | Auto-detected; no configuration needed |
| Linux | CUDA (via whisper.cpp) | Build with `WHISPER_CUDA=1` at install time |
| Windows | CUDA or CPU only | `WHISPER_CUDA=1` at build time |

whisper.cpp handles compute precision selection automatically — no `compute_type` parameter is needed.
