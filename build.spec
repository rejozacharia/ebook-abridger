# -*- mode: python ; coding: utf-8 -*-

import os
from PyInstaller.building.build_main import Analysis, PYZ, EXE, COLLECT

# ─── Paths ────────────────────────────────────────────────────────────────
proj_root      = os.getcwd()
resources_dir  = os.path.join(proj_root, 'resources')

# ─── Shared data files ─────────────────────────────────────────────────────
# (only bundle user_settings.json if it actually exists)
common_datas = [
    (os.path.join(proj_root, 'config.yaml'),        '.'),
    (os.path.join(proj_root, '.env.template'),      '.'),
    (os.path.join(resources_dir, 'README.txt'),     '.'),
]
user_settings = os.path.join(proj_root, 'user_settings.json')
if os.path.exists(user_settings):
    common_datas.append((user_settings, '.'))

# ─── Build GUI EXE ─────────────────────────────────────────────────────────
a_gui = Analysis(
    ['gui.py'],
    pathex=[proj_root],
    binaries=[],
    datas=common_datas,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[]
)

pyz_gui = PYZ(a_gui.pure, a_gui.zipped_data, cipher=None)

exe_gui = EXE(
    pyz_gui,
    a_gui.scripts,
    [],
    exclude_binaries=True,
    name='ebook_abridger_gui',
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    contents_directory='.',  
    icon=os.path.join(resources_dir, 'ebookabridger.ico')
)

# ─── Build CLI EXE ─────────────────────────────────────────────────────────
a_cli = Analysis(
    ['main.py'],
    pathex=[proj_root],
    binaries=[],
    datas=common_datas,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[]
)

pyz_cli = PYZ(a_cli.pure, a_cli.zipped_data, cipher=None)

exe_cli = EXE(
    pyz_cli,
    a_cli.scripts,
    [],
    exclude_binaries=True,
    name='ebook_abridger_cli',
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    contents_directory='.',  
    icon=os.path.join(resources_dir, 'ebookabridger.ico')
)

# ─── Collect everything into one folder ────────────────────────────────────
coll = COLLECT(
    exe_gui,
    exe_cli,
    a_gui.binaries + a_cli.binaries,
    a_gui.zipfiles + a_cli.zipfiles,
    a_gui.datas + a_cli.datas,
    strip=False,
    upx=True,
    name='ebook_abridger'
)
