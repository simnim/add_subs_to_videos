# GUI Features

The GUI is a PySide6 desktop application launched via `add-subs-to-videos-gui`. It wraps the same `process_directory` pipeline as the CLI, with drag-and-drop folder selection, live progress bars, a per-file transcript log, and unattended auto re-run.

## Launching

```bash
add-subs-to-videos-gui         # after pip/pipx install
uv run add-subs-to-videos-gui  # from source
```

## Main Window Layout

```
┌──────────────────────────────────────────────┐
│  [Drop Zone: drag folder here or click]      │
├──────────────────────────────────────────────┤
│  Overall: [████████░░░░░░░░░░░░] 40%         │
│  Current: [████░░░░░░░░░░░░░░░░] 20%         │
├──────────────────────────────────────────────┤
│  File               Status      Log          │
│  documentary.mp4    Processing  📋           │
│  lecture.mkv        Pending     📋           │
│  tutorial.mp4       Done        📋           │
├──────────────────────────────────────────────┤
│  Model: [medium ▾]  Language: [Auto ▾]       │
│  Threads: [8 ▲▼]  □ Force re-run  □ Debug    │
│  □ Auto re-run                               │
├──────────────────────────────────────────────┤
│  [Run]  [Cancel]                             │
│  Transcript log output...                    │
└──────────────────────────────────────────────┘
```

## Drop Zone

The drop zone accepts:
- **Drag and drop:** Drag a folder or video file onto the window
- **Click to browse:** Opens a folder picker dialog
- **Keyboard:** Tab to focus, then Return or Space to open the dialog

The current selected path is shown with automatic text elision for long paths.

Selecting a folder saves it to `~/.config/add-subs-to-videos/config.toml` immediately.

## Model Dropdown

Shows all available whisper models. Each entry displays an icon indicating download status:
- **✓** (checkmark) — model is already downloaded and cached locally
- **↓** (download arrow) — model has not been downloaded yet

Selecting a model that hasn't been downloaded triggers an automatic download before transcription begins, with a progress indicator in the model dropdown area.

Available models: `tiny`, `base`, `small`, `medium`, `large-v3`

## Language Dropdown

- **Auto-detect** (default) — whisper.cpp infers the language from the audio
- **99 language codes** — covers the full language table supported by whisper.cpp (e.g. `en`, `es`, `fr`, `de`, `ja`, `zh`, ...)

Pinning a language improves speed slightly and avoids rare misdetections.

## Controls

| Control | Description |
|---------|-------------|
| **Threads spinbox** | Range: 1 to the number of available CPU cores |
| **Force re-run** | Re-transcribe files that already have a `.srt` |
| **Debug logging** | Enables verbose output in the transcript log (detected language, confidence %) |
| **Auto re-run** | Automatically rescan and re-run 10 minutes after each completed run |

All control values are persisted to config on window close.

## Progress Bars

Two progress bars are shown during a run:
- **Overall:** Tracks total progress across all files (scaled to sub-file precision using 1000-unit granularity internally)
- **Current file:** Shows 0–100% for the file currently being transcribed, based on ffprobe-reported duration

## File Table

The file table lists all discovered video files with:
- **Filename** — relative path within the scanned directory
- **Status** — one of: `Pending`, `Processing`, `Done`, `Skipped`, `Failed`
- **Log icon** — click the 📋 icon to open a dialog showing that file's live transcript output

The table is populated by an asynchronous `_FileScanThread` that scans the folder immediately after selection, before the Run button is clicked.

## Per-File Log Dialog

Clicking the log icon opens a scrolling text dialog showing the transcription segments as they arrive:

```
[00:00 --> 00:04] Welcome to today's lecture.
[00:04 --> 00:09] We'll be covering the fundamentals of...
```

The dialog stays live during processing and can be opened for any file (including completed ones).

## Run and Cancel Buttons

- **Run** — starts transcription. Disabled while a run is in progress.
- **Cancel** — stops the active transcription (or cancels the auto re-run countdown). Cancellation is cooperative: the current segment finishes before the run stops.

## Auto Re-run

When the **Auto re-run** checkbox is enabled, after each successful run the Run button relabels to a countdown:

```
Run (auto re-run in 9:58)
```

After 10 minutes, the app automatically rescans the folder and starts a new run. This lets the app run unattended, picking up new video files as they appear in the watched folder.

Clicking **Cancel** during the countdown cancels the pending re-run without stopping the app.

## Transcript Log (Bottom Panel)

The main transcript log at the bottom of the window shows:
- Model download progress
- Per-file start/completion messages
- The same segment output that appears in per-file dialogs
- Error messages if a file fails

This log aggregates output from all files in a single scrolling view.

## Color Scheme

The app forces a light color scheme regardless of system settings, for consistent readability on all platforms.

## Threading Model

The GUI never runs transcription on the main thread. `_WorkerThread` (a `QThread`) runs `process_directory` in the background and relays updates to the UI via Qt signals:

| Signal | Payload | Purpose |
|--------|---------|---------|
| `log_line` | string | Append text to the transcript log |
| `progress` | `ProgressEvent` | Update file table status and overall progress bar |
| `file_progress` | float (0–1) | Update current-file progress bar |
| `model_progress` | float (0–1) | Update model download indicator |
| `finished_run` | bool (cancelled?) | Re-enable Run button; start countdown if applicable |

A separate `_FileScanThread` handles asynchronous folder scanning so the UI stays responsive while video discovery runs.
