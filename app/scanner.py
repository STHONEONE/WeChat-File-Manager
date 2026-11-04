"""Read-only traversal with metadata diffing and atomic per-account updates."""
import os
import stat
import time
from pathlib import Path
from app.paths import canonical,linked,EXTENSIONS,month_of
from app.snapshots import signature,indexed_signature,managed,safe_parent,account_for

class ScanCancelled(Exception):
    pass

def upsert_file(db,path,root,name,s,old):
    sig=signature(s)
    if old and not old['missing'] and indexed_signature(old)==sig:
        return False
    if old and old['identity']!=sig[3]:
        db.execute("UPDATE files SET note='',tags='',favorite=0 WHERE path=?",(path,))
    db.execute("""INSERT INTO files(path,account,name,category,size,mtime,month,identity,seen,mtime_ns,ctime_ns)
                  VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET
                  account=excluded.account,name=excluded.name,category=excluded.category,
                  size=excluded.size,mtime=excluded.mtime,month=excluded.month,
                  identity=excluded.identity,mtime_ns=excluded.mtime_ns,ctime_ns=excluded.ctime_ns,
                  missing=0,seen=excluded.seen""",
               (path,root,name,EXTENSIONS.get(Path(name).suffix.lower(),'其他文件'),
                s.st_size,s.st_mtime,month_of(path,s.st_mtime),sig[3],'v12',s.st_mtime_ns,s.st_ctime_ns))
    db.execute('UPDATE hash_cache SET valid=0 WHERE path=? AND valid=1',(path,))
    return True

class ScannerMixin:
    def scan(self,progress=lambda text:None,cancelled=lambda:False):
        with self._index_lock:
            return self._scan(progress,cancelled)

    def _scan(self,progress,cancelled):
        result={'files':0,'errors':[],'cancelled':False,'changed':0,'unchanged':0,'deleted':0,'directory_updates':0,'scanned':0}
        self.set_setting('state:scan',dict(result,time=time.time(),complete=False,running=True))
        last_progress=0.
        for account in self.accounts():
            root=account['path'];progress(f'扫描账号：{account["name"]}；已扫描 {result["scanned"]:,} 个文件')
            errors=[];directories={};records={}
            if not Path(root).is_dir() or linked(root):
                errors.append(root+'：目录不可访问，保留原索引')
            else:
                def onerror(e):errors.append(str(e))
                for current,dirs,names in os.walk(root,followlinks=False,onerror=onerror):
                    if cancelled():
                        result['cancelled']=True;self.set_setting('state:scan',dict(result,time=time.time(),complete=False));return result
                    keep=[]
                    for directory in dirs:
                        try:
                            info=os.lstat(Path(current)/directory)
                            if not stat.S_ISLNK(info.st_mode) and not getattr(info,'st_file_attributes',0)&0x400:keep.append(directory)
                        except OSError as e:onerror(e)
                    dirs[:]=keep
                    key=canonical(current);directories[key]=[0,0]
                    for name in names:
                        if cancelled():
                            result['cancelled']=True;self.set_setting('state:scan',dict(result,time=time.time(),complete=False));return result
                        p=Path(current)/name
                        try:
                            info=os.lstat(p)
                            if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:continue
                            s=p.stat();result['scanned']+=1
                            directories[key][0]+=1;directories[key][1]+=s.st_size
                            if managed(p,root):records[canonical(p)]=(name,s)
                        except OSError as e:onerror(e)
                        now=time.monotonic()
                        if now-last_progress>=.15:
                            progress(f'扫描账号：{account["name"]}；已扫描 {result["scanned"]:,} 个文件；当前目录：{current}')
                            last_progress=now
                for path in sorted(directories,key=lambda p:len(Path(p).parts),reverse=True):
                    parent=canonical(Path(path).parent)
                    if parent in directories:
                        directories[parent][0]+=directories[path][0];directories[parent][1]+=directories[path][1]
            if cancelled():
                result['cancelled']=True;self.set_setting('state:scan',dict(result,time=time.time(),complete=False));return result
            progress(f'提交账号索引：{account["name"]}；{len(records):,} 个可管理文件')
            counts={'changed':0,'unchanged':0,'deleted':0,'directory_updates':0}
            try:
                with self.connect() as db:
                    previous={r['path']:dict(r) for r in db.execute('SELECT * FROM files WHERE account=?',(root,))}
                    old_dirs={r['path']:dict(r) for r in db.execute('SELECT * FROM directories WHERE account=?',(root,))}
                    aliases={r[0][6:]:r[1] for r in db.execute("SELECT key,value FROM settings WHERE key LIKE 'alias:%'")}
                    notes={r[0][8:]:r[1] for r in db.execute("SELECT key,value FROM settings WHERE key LIKE 'dirnote:%'")}
                    for i,(path,(name,s)) in enumerate(records.items()):
                        if i%128==0 and cancelled():raise ScanCancelled()
                        changed=upsert_file(db,path,root,name,s,previous.get(path))
                        counts['changed' if changed else 'unchanged']+=1
                    if not errors:
                        missing=[(p,) for p,r in previous.items() if p not in records and not r['missing']]
                        db.executemany('UPDATE files SET missing=1 WHERE path=?',missing)
                        db.executemany('UPDATE hash_cache SET valid=0 WHERE path=? AND valid=1',missing)
                        counts['deleted']=len(missing)
                        db.executemany('DELETE FROM directories WHERE path=?',[(p,) for p in old_dirs if p not in directories])
                    for i,(path,(count,size)) in enumerate(directories.items()):
                        if i%128==0 and cancelled():raise ScanCancelled()
                        parent=canonical(Path(path).parent);old=old_dirs.get(path)
                        if old and (old['count'],old['size'],old['parent'])==(count,size,parent):continue
                        alias=aliases.get(path,old['alias'] if old else '')
                        db.execute('''INSERT INTO directories(path,account,alias,count,size,parent,note) VALUES (?,?,?,?,?,?,?)
                            ON CONFLICT(path) DO UPDATE SET count=excluded.count,size=excluded.size,parent=excluded.parent''',(path,root,alias,count,size,parent,notes.get(path,old.get('note','') if old else '')))
                        counts['directory_updates']+=1
                    now=time.time()
                    db.execute('''INSERT INTO account_scan_state(account,scanned_at,complete,error,last_success) VALUES (?,?,?,?,?)
                        ON CONFLICT(account) DO UPDATE SET scanned_at=excluded.scanned_at,complete=excluded.complete,error=excluded.error,
                        last_success=CASE WHEN excluded.complete=1 THEN excluded.last_success ELSE account_scan_state.last_success END''',(root,now,int(not errors),'\n'.join(errors[:20]),now if not errors else None))
            except ScanCancelled:
                result['cancelled']=True;self.set_setting('state:scan',dict(result,time=time.time(),complete=False));return result
            for key,value in counts.items():result[key]+=value
            result['files']+=len(records);result['errors'].extend(errors)
        self.set_setting('state:scan',dict(result,time=time.time(),complete=not result['errors']))
        if not result['errors']:self.set_setting('scan:last_success',time.time())
        return result

    def update_paths(self,paths,cancelled=lambda:False):
        """Coalesced file events; directory events/overflow use scan() instead."""
        accounts=self.accounts();result={'changed':0,'unchanged':0,'deleted':0,'errors':[],'cancelled':False}
        with self._index_lock:
            try:
                with self.connect() as db:
                    for path in sorted({canonical(p) for p in paths}):
                        if cancelled():raise ScanCancelled()
                        root=account_for(path,accounts)
                        if not root or not managed(path,root):continue
                        if not safe_parent(path,root):
                            result['errors'].append(path+'：父目录不可访问或为目录链接，保留旧状态');continue
                        oldrow=db.execute('SELECT * FROM files WHERE path=?',(path,)).fetchone()
                        old=dict(oldrow) if oldrow else None
                        before_size=old['size'] if old and not old['missing'] else 0
                        before_count=int(bool(old and not old['missing']))
                        try:
                            p=Path(path)
                            if p.is_symlink() or linked(p) and p.exists():continue
                            s=p.stat()
                            if not p.is_file():continue
                        except FileNotFoundError:
                            if old and not old['missing']:
                                db.execute('UPDATE files SET missing=1 WHERE path=?',(path,))
                                db.execute('UPDATE hash_cache SET valid=0 WHERE path=?',(path,))
                                result['deleted']+=1;after_count=0;after_size=0
                            else:continue
                        except OSError as e:result['errors'].append(str(e));continue
                        else:
                            if not upsert_file(db,path,root,p.name,s,old):result['unchanged']+=1;continue
                            result['changed']+=1;after_count=1;after_size=s.st_size
                        parent=Path(path).parent
                        while parent.is_relative_to(Path(root)):
                            key=canonical(parent)
                            db.execute('''INSERT INTO directories(path,account,alias,count,size,parent) VALUES (?,?,'',?,?,?)
                                ON CONFLICT(path) DO UPDATE SET count=max(0,count+excluded.count),size=max(0,size+excluded.size)''',
                                (key,root,after_count-before_count,after_size-before_size,canonical(parent.parent)))
                            if canonical(parent)==root:break
                            parent=parent.parent
                    db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('state:event-time',str(time.time())))
            except ScanCancelled:
                return dict(changed=0,unchanged=0,deleted=0,errors=[],cancelled=True)
        return result
