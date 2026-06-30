# Snapcraft Packaging

The snap package is the primary distribution mechanism for Linux users. It bundles all dependencies — including ffmpeg, Qt libraries, and the compiled whisper.cpp extension — into a single self-contained package installable on any modern Ubuntu or snap-compatible system.

## What the Snap Includes

The snap bundles:
- The Python application and all its dependencies (including `pywhispercpp`, compiled C++ extension)
- ffmpeg and ffprobe (via `stage-packages`)
- PySide6 and the full Qt6 runtime
- BLAS/LAPACK and OpenMP libraries for whisper.cpp acceleration

No `brew install`, `apt install`, or external Python environment is needed.

## snap/snapcraft.yaml Breakdown

```yaml
name: add-subs-to-videos
base: core24
confinement: strict
```

- **base: core24** — built on Ubuntu 24.04 LTS runtime, providing a consistent, long-lived foundation
- **confinement: strict** — app runs in a sandboxed environment with explicit interface plugs

### Apps

Two apps are declared:

```yaml
apps:
  add-subs-to-videos:
    command: bin/add_subs_to_videos
    plugs: [home, removable-media, network]

  add-subs-to-videos-gui:
    command: bin/add-subs-to-videos-gui
    extensions: [gnome]
    plugs: [home, removable-media, network]
```

- The CLI app requires `home` (read user files), `removable-media` (access external drives), and `network` (download models)
- The GUI app additionally uses the `gnome` extension, which pulls in GTK theming, font rendering, and desktop integration without manual configuration

### Build Process

The snap uses the Python plugin with a CMake build for the C++ extension:

```yaml
parts:
  add-subs-to-videos:
    plugin: python
    source: .
    build-packages: [cmake, ...]
    stage-packages: [ffmpeg, libqt6..., libgomp1, ...]
```

`snapcraft build` compiles `pywhispercpp`'s whisper.cpp C++ extension from source during snap assembly. This is why the snap build takes longer than a simple pip install — it's doing a full native compile.

The `stage-packages` field pulls ffmpeg and Qt from Ubuntu's apt repositories and includes them in the final snap image.

### PATH Setup at Runtime

Because the snap bundles ffmpeg at `$SNAP/usr/bin`, the runtime code must add this to `PATH` before invoking ffmpeg. This is handled in `runtime_paths.py`:

```python
snap_bin = os.environ.get("SNAP") and Path(os.environ["SNAP"]) / "usr/bin"
if snap_bin and snap_bin.exists():
    _prepend_to_path(snap_bin)
```

The `$SNAP` environment variable is set automatically by snapd when the app is running inside the snap environment.

## CI/CD: How the Snap Gets Built and Published

The workflow in `.github/workflows/snap.yml` fires on every GitHub Release:

1. **Build:** `snapcore/action-build` runs snapcraft in a clean Ubuntu environment and produces the `.snap` file
2. **Publish:** `snapcore/action-publish` uploads to the Snap Store's `stable` channel using credentials stored in the `SNAPCRAFT_STORE_CREDENTIALS` secret

The snap is published to the stable channel immediately on release — there is no staging or beta channel step in the current workflow.

## One-Time Setup (for maintainers)

Before the first snap release:

```bash
snap install snapcraft --classic
snapcraft login
snapcraft register add-subs-to-videos
snapcraft export-login --snaps add-subs-to-videos --acls package_access,package_push,package_release -
# Paste the output into the SNAPCRAFT_STORE_CREDENTIALS GitHub secret
```

## Testing the Snap Locally

```bash
snapcraft                          # build the snap (takes several minutes)
sudo snap install add-subs-to-videos_*.snap --dangerous   # install locally
add-subs-to-videos /path/to/videos --model medium
add-subs-to-videos-gui
```

The `--dangerous` flag is needed because the snap isn't signed by the Snap Store.

## Snap Confinement and Permissions

With strict confinement, the snap cannot access arbitrary filesystem paths by default. Users must connect the `removable-media` interface to access external drives:

```bash
sudo snap connect add-subs-to-videos:removable-media
```

Network access (for model downloads) is granted via the `network` plug automatically.
