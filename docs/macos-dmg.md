# macOS DMG Packaging

The macOS release ships as a `.dmg` containing a self-contained GUI `.app` bundle and a standalone CLI binary. Neither requires Python, Homebrew, or ffmpeg to be installed by the end user.

## What Gets Built

```
Add Subs to Videos-<version>.dmg
├── Add Subs to Videos.app     # GUI app bundle
├── add_subs_to_videos         # Standalone CLI binary directory
│   └── add_subs_to_videos     # Executable
└── Install CLI.command        # Helper script to symlink CLI into /usr/local/bin
```

## Build Script: packaging/mac/build_mac.sh

Run locally with:

```bash
bash packaging/mac/build_mac.sh
```

**Requirements:** `brew install ffmpeg cmake librsvg create-dmg dylibbundler`

### Steps the Script Performs

**1. Icon generation**

Converts `assets/icon.svg` into a macOS `.icns` bundle:

```bash
rsvg-convert -w 1024 -h 1024 assets/icon.svg -o icon.png
# Generates all @1x and @2x sizes: 16, 32, 128, 256, 512
sips -z <size> <size> icon.png ...
iconutil -c icns icon.iconset
```

**2. PyInstaller build**

Runs PyInstaller using `packaging/mac/add_subs_to_videos.spec`:

```bash
uv run pyinstaller packaging/mac/add_subs_to_videos.spec
```

This produces two build artifacts in `dist/`:
- `Add Subs to Videos.app` — GUI bundle (`console=False`, uses `gui_launcher.py`)
- `add_subs_to_videos/` — CLI onedir bundle (`console=True`, uses `cli_launcher.py`)

Both bundles collect all `pywhispercpp` and `PySide6` binaries and data files.

**3. ffmpeg bundling**

Calls `packaging/mac/bundle_ffmpeg.sh` on both bundles:

```bash
bash packaging/mac/bundle_ffmpeg.sh "dist/Add Subs to Videos.app/Contents/MacOS"
bash packaging/mac/bundle_ffmpeg.sh "dist/add_subs_to_videos"
```

See [ffmpeg bundling](#ffmpeg-bundling-bundle_ffmpegsh) below.

**4. DMG creation**

Uses `create-dmg` to assemble the final `.dmg`:

```bash
create-dmg \
  --volname "Add Subs to Videos" \
  --app-drop-link <x> <y> \
  --icon "Add Subs to Videos.app" <x> <y> \
  ...
  "Add Subs to Videos-<version>.dmg" dist/dmg/
```

## ffmpeg Bundling: bundle_ffmpeg.sh

`packaging/mac/bundle_ffmpeg.sh <target_dir>` makes the target directory fully self-contained with respect to ffmpeg.

**Process:**

1. Locates `ffmpeg` and `ffprobe` via `command -v` (finds Homebrew's versions)
2. Copies both binaries to `<target_dir>/ffmpeg-bin/`
3. Runs `dylibbundler` to resolve and copy all dylib dependencies:
   ```bash
   dylibbundler -od -b -x ffmpeg-bin/ffmpeg -d ffmpeg-bin/libs/ -p @executable_path/libs/
   dylibbundler -od -b -x ffmpeg-bin/ffprobe -d ffmpeg-bin/libs/ -p @executable_path/libs/
   ```
4. Rewrites `@rpath` and absolute load paths to `@executable_path/libs/...` so the binaries are relocatable

The result: `ffmpeg-bin/` contains `ffmpeg`, `ffprobe`, and a `libs/` subdirectory with every required `.dylib`. No system ffmpeg is needed at runtime.

## How Bundled ffmpeg Gets Found at Runtime

`runtime_paths.py` runs at startup (called from both `cli.py:main()` and `gui.py:main()`):

```python
def ensure_bundled_ffmpeg_on_path():
    # For PyInstaller .app bundles, sys.executable is inside Contents/MacOS/
    bundle_dir = Path(sys.executable).parent
    ffmpeg_bin = bundle_dir / "ffmpeg-bin"
    if ffmpeg_bin.exists():
        _prepend_to_path(ffmpeg_bin)
```

This prepends `ffmpeg-bin/` to `PATH`, making `ffprobe` (used for duration probing) and pywhispercpp's internal `ffmpeg` call (used to decode non-WAV media) resolve to the bundled versions.

## PyInstaller Spec: add_subs_to_videos.spec

The spec file defines two Analysis objects, one for the GUI and one for the CLI:

- **GUI:** Entry point `gui_launcher.py` → `add_subs_to_videos.gui:main`
- **CLI:** Entry point `cli_launcher.py` → `add_subs_to_videos.cli:main`

Both collect:
```python
datas = collect_data_files("pywhispercpp") + collect_data_files("PySide6")
binaries = collect_dynamic_libs("pywhispercpp") + collect_dynamic_libs("PySide6")
```

The CLI uses `onedir` mode (not `onefile`) so that `ffmpeg-bin/` can sit alongside the executable — `onefile` mode extracts to a temp dir at runtime, which would break the relative path logic.

## CI/CD: mac-release.yml

Fires on every GitHub Release:

1. Install Homebrew dependencies: `ffmpeg cmake librsvg create-dmg dylibbundler`
2. `uv sync --extra gui` to install PySide6
3. Add PyInstaller to dev dependencies
4. Run `bash packaging/mac/build_mac.sh`
5. Upload the resulting `.dmg` to the GitHub release with `gh release upload`

Required permission: `contents: write` (to upload to the release).

## Install CLI.command

A double-clickable helper script included in the DMG. When the user runs it, it creates a symlink:

```bash
ln -sf /Applications/Add\ Subs\ to\ Videos.app/Contents/MacOS/add_subs_to_videos /usr/local/bin/add_subs_to_videos
```

This lets users run `add_subs_to_videos` from any terminal after dragging the app to `/Applications`.
