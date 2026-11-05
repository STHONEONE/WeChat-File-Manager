# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

a = Analysis(['run.py'], pathex=[], binaries=[],
             datas=[('licenses','licenses'),('assets','assets')], hiddenimports=[],
             hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False)
# Do not redistribute accidentally discovered ICU copies from unrelated PATH tools.
# Preserve QtPdf: the V1.4 PDF first-page preview loads PySide6.QtPdf at runtime.
a.binaries = [b for b in a.binaries if Path(b[0]).name.lower() not in {
    'icuuc.dll','icudt78.dll',
    # Unused virtual keyboard is not part of this desktop app.
    'qtvirtualkeyboardplugin.dll','qt6virtualkeyboard.dll'}]
pyz = PYZ(a.pure)
exe = EXE(pyz,a.scripts,[],exclude_binaries=True,name='WeChatFileManager',
          console=False,debug=False,strip=False,upx=False,icon='assets/app.ico')
coll = COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='WeChatFileManager')
