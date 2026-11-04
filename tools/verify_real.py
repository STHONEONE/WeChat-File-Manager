"""Read-only verification against local WeChat folder; output remains local."""
import json
import os
import time
from pathlib import Path
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtWidgets import QApplication
from app.core import Store
from app.main import Window

out=Path('data'); out.mkdir(exist_ok=True)
s=Store(out/'verification.sqlite'); s.add('D:/xwechat_files')
t=time.perf_counter(); result=s.scan(); elapsed=time.perf_counter()-t
summary={'scan_seconds':round(elapsed,2),'result':result,'accounts':len(s.accounts()),'categories':{}}
for r in s.search():summary['categories'][r['category']]=summary['categories'].get(r['category'],0)+1
summary['directory_count']=len(s.directories())
app=QApplication([]); w=Window(s,auto=False); w.show(); app.processEvents()
w.grab().save('docs/界面预览.png'); w.close()
Path('docs/实际扫描结果.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False))
