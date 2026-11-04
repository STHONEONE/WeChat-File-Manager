# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

a = Analysis(['run.py'], pathex=[], binaries=[],
             datas=[('licenses','licenses'),('assets','assets')], hiddenimports=[],
             hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False)
# Qt uses Windows' built-in unversioned ICU. Other tools on PATH may ship
# incompatible DLLs with the same name; never redistribute those accidental hits.
a.binaries = [b for b in a.binaries if Path(b[0]).name.lower() not in {
    'icuuc.dll','icudt78.dll',
    # Unused PDF and virtual-keyboard plugins are outside this app's scope.
    'qpdf.dll','qt6pdf.dll','qtvirtualkeyboardplugin.dll','qt6virtualkeyboard.dll'}]
pyz = PYZ(a.pure)
exe = EXE(pyz,a.scripts,[],exclude_binaries=True,name='WeChatFileManager',
          console=False,debug=False,strip=False,upx=False,icon='assets/app.ico')
coll = COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='WeChatFileManager')
