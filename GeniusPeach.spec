# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

# ui/web = HTML/CSS/JS do painel (QWebEngineView) + o build local do
# Tailwind. Precisa manter a MESMA profundidade relativa no bundle porque o
# dashboard.html referencia as fontes como '../../assets/...' — em
# _internal/ui/web/ isso resolve para _internal/assets/.
datas = [('assets', 'assets'), ('ui/web', 'ui/web')]
binaries = []
hiddenimports = [
    'PySide6.QtWebEngineWidgets',
    'PySide6.QtWebEngineCore',
    'PySide6.QtWebChannel',
    'PySide6.QtNetwork',
    'PySide6.QtPrintSupport',
]
tmp_ret = collect_all('faster_whisper')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('torch')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('PySide6')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    [],
    exclude_binaries=True,
    name='GeniusPeach',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
    version='version_info.txt',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    # Comprimir os binários do Chromium com UPX costuma produzir um
    # QtWebEngineProcess que não sobe (o painel abre em branco, sem erro).
    upx_exclude=[
        'QtWebEngineProcess.exe',
        'Qt6WebEngineCore.dll',
        'Qt6WebEngineWidgets.dll',
        'Qt6WebEngineQuick.dll',
    ],
    name='GeniusPeach',
)
