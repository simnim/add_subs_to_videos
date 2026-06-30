# Python Installation

For users with Python 3.12+ already installed, `add_subs_to_videos` can be installed directly from PyPI. This is the most flexible installation method and works on any platform.

## Prerequisites

- Python 3.12 or higher
- A C++ compiler (for building `pywhispercpp`'s whisper.cpp extension):
  - **macOS:** Xcode Command Line Tools (`xcode-select --install`)
  - **Linux:** `gcc` / `g++` and `cmake`
  - **Windows:** Visual Studio Build Tools with C++ workload
- ffmpeg and ffprobe on `PATH`:
  - macOS: `brew install ffmpeg`
  - Ubuntu/Debian: `sudo apt install ffmpeg`
  - Windows: Download from https://ffmpeg.org and add to PATH

## Installing via pipx (Recommended)

[pipx](https://pipx.pypa.io) installs CLI tools in isolated environments, keeping your system Python clean:

```bash
pipx install add_subs_to_videos
add_subs_to_videos --help
```

To include the GUI:

```bash
pipx install "add_subs_to_videos[gui]"
add-subs-to-videos-gui
```

## Installing via pip

```bash
pip install add_subs_to_videos          # CLI only
pip install "add_subs_to_videos[gui]"   # CLI + GUI (installs PySide6)
```

Installing into a virtual environment is strongly recommended:

```bash
python -m venv .venv
source .venv/bin/activate               # Windows: .venv\Scripts\activate
pip install add_subs_to_videos
```

## Installing with uv (for development)

[uv](https://github.com/astral-sh/uv) is used for development and is the fastest way to get started from source:

```bash
git clone https://github.com/simnim/add_subs_to_videos
cd add_subs_to_videos
uv sync                          # installs all core dependencies
uv sync --extra gui              # also installs PySide6
uv run add_subs_to_videos --help
uv run add-subs-to-videos-gui
```

`uv sync` compiles `pywhispercpp`'s C++ extension during installation — this can take a few minutes on first run.

## GPU Acceleration

### macOS (Metal)

Metal acceleration is auto-detected by whisper.cpp — no extra steps needed. The compiled extension will use the GPU automatically when available.

### Linux (CUDA)

`pywhispercpp` must be compiled with CUDA support enabled:

```bash
WHISPER_CUDA=1 pip install add_subs_to_videos
# or with uv:
WHISPER_CUDA=1 uv sync
```

This requires the NVIDIA CUDA toolkit to be installed before building.

## How PyPI Publishing Works

The package is built and published automatically when a GitHub Release is created. The workflow in `.github/workflows/publish.yml`:

1. Installs uv and system dependencies (ffmpeg, cmake)
2. Builds a wheel: `uv build`
3. Publishes: `uv publish --token $PYPI_TOKEN`

The wheel contains the Python source but **not** the compiled C++ extension — `pywhispercpp` handles its own build during `pip install`. This means `pip install` always compiles whisper.cpp locally for the target platform.

## Package Structure

```
add_subs_to_videos/
├── cli.py           # Entry point: add_subs_to_videos
├── gui.py           # Entry point: add-subs-to-videos-gui  [gui extra]
├── transcribe.py    # Core transcription pipeline
├── files.py         # Video file discovery
├── config.py        # Shared config persistence
├── srt.py           # SRT formatting
└── runtime_paths.py # Bundled ffmpeg detection
```

Entry points registered in `pyproject.toml`:

```toml
[project.scripts]
add_subs_to_videos = "add_subs_to_videos.cli:main"
add-subs-to-videos-gui = "add_subs_to_videos.gui:main"
```

The package can also be run as a module:

```bash
python -m add_subs_to_videos /path/to/videos
```

## Upgrading

```bash
pipx upgrade add_subs_to_videos
# or
pip install --upgrade add_subs_to_videos
# or (from source)
git pull && uv sync
```

## Uninstalling

```bash
pipx uninstall add_subs_to_videos
# or
pip uninstall add_subs_to_videos
```

Saved preferences are stored separately at `~/.config/add-subs-to-videos/config.toml` and are not removed on uninstall.
