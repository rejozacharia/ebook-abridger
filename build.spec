# -*- mode: python ; coding: utf-8 -*-

import sys
from PyInstaller.utils.hooks import collect_all
from PyInstaller.building.build_main import Analysis, PYZ, EXE, COLLECT

# Path to the GUI script
script_path = 'gui.py'

# Non-Python data files to bundle alongside the executable
datas = [
    ('config.yaml', '.'),
    ('.env', '.'),
    ('user_settings.json', '.')
]

# Hidden imports if PyInstaller misses any
hidden_imports = []

# Cipher (unused)
block_cipher = None

# --- Analysis ---
a = Analysis(
    [script_path],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[]
)

# --- PYZ ---
pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher
)

# --- EXE (onefile) ---
exe = EXE(
    pyz,
    a.scripts,
    [],               # no additional binaries
    exclude_binaries=True,
    name='ebook_abridger_gui',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,    # GUI mode (no console)
    icon='ebookabridger.ico'  # Optional: path to your .ico
)

# --- COLLECT ---
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name='ebook_abridger_gui'
)

# To create the CLI executable, copy this spec, change:
#   script_path = 'main.py'
#   console=True in EXE
#   name='ebook_abridger_cli'
# then run: pyinstaller build.spec
