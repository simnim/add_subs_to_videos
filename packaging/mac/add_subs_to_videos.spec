import os
from PyInstaller.utils.hooks import collect_all

REPO_ROOT = os.path.abspath(os.path.join(SPECPATH, '..', '..'))
SRC_PATH = os.path.join(REPO_ROOT, 'src')
ICON_PATH = os.path.join(REPO_ROOT, 'assets', 'icon.icns')
APP_VERSION = os.environ.get('APP_VERSION', '0.0.0')

datas, binaries, hiddenimports = [], [], []

for pkg in ('pywhispercpp', 'PySide6'):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

# GUI app bundle
gui_a = Analysis(
    [os.path.join(SPECPATH, 'gui_launcher.py')],
    pathex=[SRC_PATH],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + ['add_subs_to_videos'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
gui_pyz = PYZ(gui_a.pure)
gui_exe = EXE(
    gui_pyz,
    gui_a.scripts,
    [],
    exclude_binaries=True,
    name='Add Subs to Videos',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON_PATH,
)
gui_coll = COLLECT(
    gui_exe,
    gui_a.binaries,
    gui_a.zipfiles,
    gui_a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Add Subs to Videos',
)
app = BUNDLE(
    gui_coll,
    name='Add Subs to Videos.app',
    icon=ICON_PATH,
    bundle_identifier='com.simnim.add-subs-to-videos',
    info_plist={
        'NSPrincipalClass': 'NSApplication',
        'NSAppleScriptEnabled': False,
        'CFBundleShortVersionString': APP_VERSION,
    },
)

# Standalone CLI bundle, shipped alongside the .app (not nested inside it).
# Built as a onedir bundle (rather than onefile) so the bundled ffmpeg/ffprobe
# binaries (added by packaging/mac/bundle_ffmpeg.sh) can sit next to the
# executable with stable, relocatable @executable_path-relative dylib paths.
cli_a = Analysis(
    [os.path.join(SPECPATH, 'cli_launcher.py')],
    pathex=[SRC_PATH],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + ['add_subs_to_videos'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
cli_pyz = PYZ(cli_a.pure)
cli_exe = EXE(
    cli_pyz,
    cli_a.scripts,
    [],
    exclude_binaries=True,
    name='add_subs_to_videos',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
cli_coll = COLLECT(
    cli_exe,
    cli_a.binaries,
    cli_a.zipfiles,
    cli_a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='add_subs_to_videos',
)
