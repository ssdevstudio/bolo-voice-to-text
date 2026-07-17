# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — single source of truth for the build.
# Invoke via build.ps1 (which just calls `pyinstaller Bolo.spec`).

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Packages that ship runtime data files (JSON / themes / model assets) which
# PyInstaller's static analysis won't catch — bundle them explicitly.
_extra_datas = []
for pkg in (
    'indic_transliteration',  # sanscript schemes JSON
    'customtkinter',          # default themes + assets
    'pystray',                # platform icons
    'speech_recognition',     # bundled flac binaries
    'faster_whisper',         # tokenizer assets
    'huggingface_hub',        # constants / templates
):
    try:
        _extra_datas += collect_data_files(pkg)
    except Exception as e:
        print(f"[Bolo.spec] WARN: collect_data_files({pkg!r}) failed: {e}")

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('src/icon.ico', 'src'), ('src/hinglish_data.json', 'src')] + _extra_datas,
    hiddenimports=[
        'faster_whisper',
        'ctranslate2',
        'ctranslate2.converters',
        'speech_recognition',
        'pystray',
        'pystray._win32',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'keyboard',
        'customtkinter',
        'numpy',
        'scipy',
        'scipy.signal',
        'huggingface_hub',
        'pyperclip',
        'psutil',
        'win32api',
        'win32con',
        'src.onboarding',
    ] + collect_submodules('indic_transliteration'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'torch', 'torchvision', 'torchaudio',
        'transformers',
        'matplotlib', 'pandas', 'tensorflow',
        'jupyter', 'IPython', 'notebook',
        'pytest', 'tests',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Bolo',
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
    icon=['src\\icon.ico'],
)
