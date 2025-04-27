# -*- mode: python ; coding: utf-8 -*-

import os
from PyInstaller.utils.hooks import collect_all
from PyInstaller.building.build_main import Analysis, PYZ, EXE, COLLECT

proj_root = os.getcwd()   
resources_path = os.path.join(proj_root, 'resources')

# Common datas (shared by both GUI and CLI)
common_datas = [
    (os.path.join(proj_root, 'config.yaml'), '.'),
    (os.path.join(proj_root, 'user_settings.json'), '.'),
    (os.path.join(proj_root, '.env.template'), '.'),
    (os.path.join(resources_path, 'README.txt'), '.')
]

hidden_imports = []
block_cipher = None

# --- GUI BUILD ---
gui_script_path = 'gui.py'

a_gui = Analysis(
    [gui_script_path],
    pathex=['.'],
    binaries=[],
    datas=common_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[]
)

pyz_gui = PYZ(
    a_gui.pure,
    a_gui.zipped_data,
    cipher=block_cipher
)

exe_gui = EXE(
    pyz_gui,
    a_gui.scripts,
    [],
    exclude_binaries=True,
    name='ebook_abridger_gui',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # <-- GUI has NO console
    icon=os.path.join(resources_path, 'ebookabridger.ico')
)

# --- CLI BUILD ---
cli_script_path = 'main.py'  

a_cli = Analysis(
    [cli_script_path],
    pathex=['.'],
    binaries=[],
    datas=common_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[]
)

pyz_cli = PYZ(
    a_cli.pure,
    a_cli.zipped_data,
    cipher=block_cipher
)

exe_cli = EXE(
    pyz_cli,
    a_cli.scripts,
    [],
    exclude_binaries=True,
    name='ebook_abridger_cli',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # <-- CLI HAS console
    icon=os.path.join(resources_path, 'ebookabridger.ico')
)

# --- COLLECT both together ---
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
