import os
from PyInstaller.utils.hooks import collect_all

REPO_ROOT = os.path.abspath(os.path.join(SPECPATH, '..', '..'))
SRC_PATH = os.path.join(REPO_ROOT, 'src')
ICON_PATH = os.path.join(REPO_ROOT, 'assets', 'icon.icns')

datas, binaries, hiddenimports = [], [], []

for pkg in ('pywhispercpp', 'PySide6'):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

a = Analysis(
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
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
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
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Add Subs to Videos',
)
app = BUNDLE(
    coll,
    name='Add Subs to Videos.app',
    icon=ICON_PATH,
    bundle_identifier='com.simnim.add-subs-to-videos',
    info_plist={
        'NSPrincipalClass': 'NSApplication',
        'NSAppleScriptEnabled': False,
        'CFBundleShortVersionString': '1.0.0',
    },
)
