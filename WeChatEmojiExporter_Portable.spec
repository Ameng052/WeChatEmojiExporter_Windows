# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

ROOT = Path(SPECPATH).resolve()
PROJECT_ROOT = ROOT.parent

def first_existing(paths):
    for p in paths:
        p = Path(p) if p else None
        if p and p.exists():
            return p
    return None

FFMPEG_EXE = first_existing([
    Path(os.environ['FFMPEG_EXE']) if 'FFMPEG_EXE' in os.environ else None,
    ROOT / 'release_assets' / 'ffmpeg.exe',
    ROOT / 'third_party' / 'ffmpeg' / 'ffmpeg.exe',
    PROJECT_ROOT / 'tools' / 'ffmpeg' / 'ffmpeg-master-latest-win64-gpl' / 'bin' / 'ffmpeg.exe',
])
WECHAT_SETUP = first_existing([
    Path(os.environ['WECHAT_SETUP']) if 'WECHAT_SETUP' in os.environ else None,
    ROOT / 'release_assets' / 'WeChatSetup.exe',
    ROOT / 'third_party' / 'WeChatSetup.exe',
    ROOT / 'WeChatSetup.exe',
])
BINARIES = [(str(FFMPEG_EXE), 'tools\\ffmpeg\\ffmpeg-master-latest-win64-gpl\\bin')] if FFMPEG_EXE else []
DATAS = [(str(WECHAT_SETUP), '.')] if WECHAT_SETUP else []

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=BINARIES,
    datas=DATAS,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='WeChatEmojiExporter_Portable',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
