# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Eel serves the Next.js static export from frontend/out/
        ('frontend/out', 'frontend/out'),
        # Include backend package
        ('backend', 'backend'),
    ],
    hiddenimports=[
        'eel',
        'bottle',
        'geventwebsocket',
        'geventwebsocket.handler',
        'geventwebsocket.protocols.wamp',
        'gevent',
        'gevent.monkey',
        'pkg_resources',
    ],
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
    name='JARVIS',
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
    icon=['jarvis.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='JARVIS',
)
app = BUNDLE(
    coll,
    name='JARVIS.app',
    icon='jarvis.icns',
    bundle_identifier=None,
)
