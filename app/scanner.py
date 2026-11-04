import os
import time
from pathlib import Path
from app.paths import *

class ScannerMixin:
    def scan(self, progress=lambda text: None, cancelled=lambda:False):
        errors=[]; total=0; scanned=0; last_progress=0.0
        for account in self.accounts():
            progress(f'扫描账号：{account["name"]}；已扫描 {scanned:,} 个文件')
            root=account['path']; token=str(time.time_ns()); directories={}; records=[]; failed=False
            if not Path(root).is_dir() or linked(root):
                errors.append(root+'：目录不可访问，本次保留原索引状态'); continue
            def onerror(e):
                nonlocal failed
                failed=True; errors.append(str(e))
            for current, dirs, names in os.walk(root, followlinks=False, onerror=onerror):
                if cancelled(): return {'files':total,'errors':errors,'cancelled':True}
                dirs[:]=[d for d in dirs if not linked(Path(current)/d)]
                key=canonical(current); directories[key]=[0,0]
                rel=Path(current).relative_to(root)
                internal=any(p.lower() in SYSTEM for p in rel.parts)
                for name in names:
                    if cancelled(): return {'files':total,'errors':errors,'cancelled':True}
                    p=Path(current)/name
                    if linked(p): continue
                    try:
                        s=p.stat(); size=s.st_size
                        scanned+=1
                        now=time.monotonic()
                        if now-last_progress>=0.15:
                            progress(f'扫描账号：{account["name"]}；已扫描 {scanned:,} 个文件；当前目录：{current}')
                            last_progress=now
                        directories[key][0]+=1; directories[key][1]+=size
                        if internal or p.suffix.lower() in INTERNAL or p.suffix.lower().startswith('.kvdb') or not p.suffix: continue
                        identity=f'{s.st_dev}:{s.st_ino}:{getattr(s,"st_birthtime_ns",0)}'
                        records.append((canonical(p),root,name,EXTENSIONS.get(p.suffix.lower(),'其他文件'),size,s.st_mtime,month_of(p,s.st_mtime),identity,token))
                    except OSError as e: onerror(e)
            # Aggregate all files, including opaque system files, without reading contents.
            for path in sorted(directories,key=lambda x:len(Path(x).parts),reverse=True):
                parent=canonical(Path(path).parent)
                if parent in directories:
                    directories[parent][0]+=directories[path][0]; directories[parent][1]+=directories[path][1]
            if cancelled(): return {'files':total,'errors':errors,'cancelled':True}
            progress(f'保存账号索引：{account["name"]}；{len(records):,} 个可管理文件')
            with self.connect() as db:
                db.execute('DELETE FROM directories WHERE account=?',(root,)) if not failed else None
                # Keep aliases even when rebuilding current directory statistics.
                # aliases are retained separately in settings for absent/reappearing paths.
                for path,(count,size) in directories.items():
                    saved=db.execute('SELECT value FROM settings WHERE key=?',('alias:'+path,)).fetchone()
                    db.execute('INSERT INTO directories(path,account,alias,count,size,parent) VALUES (?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET count=excluded.count,size=excluded.size,parent=excluded.parent', (path,root,saved[0] if saved else '',count,size,canonical(Path(path).parent)))
                for row in records:
                    old=db.execute('SELECT identity FROM files WHERE path=?',(row[0],)).fetchone()
                    if old and old[0]!=row[7]: db.execute("UPDATE files SET note='',tags='',favorite=0 WHERE path=?",(row[0],))
                    db.execute('''INSERT INTO files(path,account,name,category,size,mtime,month,identity,seen) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET name=excluded.name,category=excluded.category,size=excluded.size,mtime=excluded.mtime,month=excluded.month,identity=excluded.identity,seen=excluded.seen,missing=0''',row)
                if not failed: db.execute('UPDATE files SET missing=1 WHERE account=? AND seen<>?',(root,token))
            total+=len(records)
        return {'files':total,'errors':errors,'cancelled':False}
