"""Read-only source scanner and local metadata store. No source mutations."""
import csv
import hashlib
import os
import re
import shutil
import sqlite3
import stat
import time
from datetime import datetime
from pathlib import Path

CATEGORIES = {'文档': 'pdf doc docx xls xlsx ppt pptx txt md rtf csv odt pdg', '图片': 'jpg jpeg png gif bmp webp tif tiff ico', '视频': 'mp4 avi mov mkv wmv flv webm', '音频': 'mp3 wav flac aac ogg m4a amr silk', '压缩文件': 'zip rar 7z tar gz bz2'}
EXTENSIONS = {'.'+ext: cat for cat, exts in CATEGORIES.items() for ext in exts.split()}
SYSTEM = {'all_users','backup','db_storage','apm_record','business','resource','cache','temp','tmp','logs','log','config','mmkv','thumb','thumbs','.thumbnails','favorite','emoticon','sns','xweb','xeditor'}
INTERNAL = {'.dat','.db','.db-wal','.db-shm','.mmkv','.crc','.kvdb','.ini','.lock','.tmp','.bak','.sqlite','.thumb','.xml'}
LABELS = {'msg':'聊天文件','file':'收到的文件','attach':'聊天附件（部分加密）','video':'聊天视频','db_storage':'聊天数据库（仅统计）','cache':'缓存（仅统计）','config':'配置（仅统计）','temp':'临时文件（仅统计）','business':'业务数据（仅统计）','resource':'资源（仅统计）','apm_record':'运行记录（仅统计）','FileStorage':'聊天资源','Image':'图片','Video':'视频','File':'收到的文件'}

def canonical(path):
    return os.path.normcase(os.path.abspath(path))

def linked(path):
    try:
        s = os.lstat(path)
        return stat.S_ISLNK(s.st_mode) or bool(getattr(s, 'st_file_attributes', 0) & 0x400)
    except OSError:
        return True

def discover(root):
    p = Path(root).absolute()
    if linked(p):
        return []
    def account(d):
        return (d/'msg').is_dir() or (d/'FileStorage').is_dir()
    if account(p):
        return [p]
    try:
        return [d for d in p.iterdir() if d.is_dir() and not linked(d) and account(d)]
    except OSError:
        return []

def candidates():
    roots = [Path('D:/xwechat_files')]
    for base in [Path.home(), Path.home()/'Documents', Path(os.environ.get('OneDrive', str(Path.home())))/'Documents']:
        roots += [base/n for n in ('xwechat_files','WeChat Files','Weixin Files')]
    return list(dict.fromkeys(str(p) for p in roots if p.is_dir()))

def month_of(path, mtime):
    # Adapted from oracis/wechat-file-organizer-gui month_of (MIT).
    for part in reversed(Path(path).parts[:-1]):
        if re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', part):
            return part
    return datetime.fromtimestamp(mtime).strftime('%Y-%m')

def human(n):
    for unit in ('B','KiB','MiB','GiB','TiB'):
        if n < 1024 or unit == 'TiB': return f'{n:,.1f} {unit}'
        n /= 1024

class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS accounts(path TEXT PRIMARY KEY, name TEXT, note TEXT DEFAULT '');
            CREATE TABLE IF NOT EXISTS directories(path TEXT PRIMARY KEY, account TEXT, alias TEXT DEFAULT '', count INTEGER DEFAULT 0, size INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, account TEXT, name TEXT, category TEXT, size INTEGER, mtime REAL, month TEXT, identity TEXT, missing INTEGER DEFAULT 0, seen TEXT, note TEXT DEFAULT '', tags TEXT DEFAULT '', favorite INTEGER DEFAULT 0);
            CREATE INDEX IF NOT EXISTS file_account ON files(account);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
            ''')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def accounts(self):
        with self.connect() as db: return [dict(r) for r in db.execute('SELECT * FROM accounts ORDER BY name')]

    def add(self, root):
        found = discover(root)
        if not found: raise ValueError('未识别到微信账号目录，请选择包含 msg 或 FileStorage 的目录，或其上一级目录。')
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('source:'+canonical(root),canonical(root)))
            for p in found:
                db.execute('INSERT OR IGNORE INTO accounts(path,name) VALUES (?,?)', (canonical(p),p.name))
        return len(found)

    def source_roots(self):
        with self.connect() as db:
            return [r[0] for r in db.execute("SELECT value FROM settings WHERE key LIKE 'source:%'")]+[a['path'] for a in self.accounts()]

    def annotate(self, path, note, tags, favorite):
        tags = ', '.join(dict.fromkeys(t.strip() for t in tags.replace('，',',').split(',') if t.strip()))
        with self.connect() as db: db.execute('UPDATE files SET note=?,tags=?,favorite=? WHERE path=?',(note,tags,int(favorite),path))

    def rename(self, path, name, note=None):
        with self.connect() as db:
            if note is not None: db.execute('UPDATE accounts SET name=?,note=? WHERE path=?',(name,note,path))
            else: db.execute('UPDATE directories SET alias=? WHERE path=?',(name,path))

    def directories(self, account=None):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM directories'+(' WHERE account=?' if account else '')+' ORDER BY path', (account,) if account else ())]

    def search(self, query='', category='', account='', favorite=False, tag='', minimum=0, maximum=None, start='', end='', directory='', missing=False):
        clauses=['f.missing=?']; args=[int(missing)]
        if query:
            clauses.append('(instr(lower(f.name),lower(?))>0 OR instr(lower(f.note),lower(?))>0 OR instr(lower(f.tags),lower(?))>0)'); args += [query]*3
        for col,val in [('category',category),('account',account)]:
            if val: clauses.append('f.'+col+'=?'); args.append(val)
        if favorite: clauses.append('f.favorite=1')
        if tag: clauses.append('instr(lower(f.tags),lower(?))>0'); args.append(tag)
        clauses.append('f.size>=?'); args.append(minimum)
        if maximum is not None: clauses.append('f.size<=?'); args.append(maximum)
        if start: clauses.append("date(f.mtime,'unixepoch','localtime')>=?"); args.append(start)
        if end: clauses.append("date(f.mtime,'unixepoch','localtime')<=?"); args.append(end)
        if directory:
            prefix=canonical(directory)+os.sep
            clauses.append('substr(f.path,1,?)=?'); args += [len(prefix),prefix]
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT f.*,a.name account_name FROM files f JOIN accounts a ON a.path=f.account WHERE '+' AND '.join(clauses)+' ORDER BY f.mtime DESC',args)]

    def scan(self, progress=lambda text: None, cancelled=lambda:False):
        errors=[]; total=0
        for account in self.accounts():
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
                    p=Path(current)/name
                    if linked(p): continue
                    try:
                        s=p.stat(); size=s.st_size
                        directories[key][0]+=1; directories[key][1]+=size
                        if internal or p.suffix.lower() in INTERNAL or p.suffix.lower().startswith('.kvdb') or not p.suffix: continue
                        identity=f'{s.st_dev}:{s.st_ino}:{getattr(s,"st_birthtime_ns",0)}'
                        records.append((canonical(p),root,name,EXTENSIONS.get(p.suffix.lower(),'其他文件'),size,s.st_mtime,month_of(p,s.st_mtime),identity,token))
                    except OSError as e: onerror(e)
                if len(directories)%100==0: progress(f'扫描 {account["name"]}：{len(directories)} 个目录，{len(records)} 个可管理文件')
            # Aggregate all files, including opaque system files, without reading contents.
            for path in sorted(directories,key=lambda x:len(Path(x).parts),reverse=True):
                parent=canonical(Path(path).parent)
                if parent in directories:
                    directories[parent][0]+=directories[path][0]; directories[parent][1]+=directories[path][1]
            with self.connect() as db:
                db.execute('DELETE FROM directories WHERE account=?',(root,)) if not failed else None
                # Keep aliases even when rebuilding current directory statistics.
                # aliases are retained separately in settings for absent/reappearing paths.
                for path,(count,size) in directories.items():
                    saved=db.execute('SELECT value FROM settings WHERE key=?',('alias:'+path,)).fetchone()
                    db.execute('INSERT INTO directories(path,account,alias,count,size) VALUES (?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET count=excluded.count,size=excluded.size', (path,root,saved[0] if saved else '',count,size))
                for row in records:
                    old=db.execute('SELECT identity FROM files WHERE path=?',(row[0],)).fetchone()
                    if old and old[0]!=row[7]: db.execute("UPDATE files SET note='',tags='',favorite=0 WHERE path=?",(row[0],))
                    db.execute('''INSERT INTO files(path,account,name,category,size,mtime,month,identity,seen) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET name=excluded.name,category=excluded.category,size=excluded.size,mtime=excluded.mtime,month=excluded.month,identity=excluded.identity,seen=excluded.seen,missing=0''',row)
                if not failed: db.execute('UPDATE files SET missing=1 WHERE account=? AND seen<>?',(root,token))
            total+=len(records)
        return {'files':total,'errors':errors,'cancelled':False}

    def alias(self, path, value):
        self.rename(path,value)
        with self.connect() as db: db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('alias:'+path,value))

    def backup(self, target):
        with self.connect() as src, sqlite3.connect(target) as dest: src.backup(dest)

def digest(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()

def export_files(rows, target, mode='类型+月份', conflict='自动更名', protected=(), progress=lambda t:None):
    target=Path(target).resolve()
    for root in protected:
        if target.is_relative_to(Path(root).resolve()): raise ValueError('导出目录不能位于微信原始目录内。')
    target.mkdir(parents=True,exist_ok=True)
    manifest=[]; failures=[]; skipped=0
    for row in rows:
        source=Path(row['path']); dest=target
        if '类型' in mode: dest/=row['category']
        if '月份' in mode: dest/=row['month']
        dest/=source.name
        for root in protected:
            if dest.resolve().is_relative_to(Path(root).resolve()): raise ValueError('目标路径经过链接指向微信原目录。')
        created=False
        try:
            dest.parent.mkdir(parents=True,exist_ok=True)
            if dest.exists() and conflict=='跳过': skipped+=1; continue
            index=1; base=dest
            while True:
                try:
                    out=dest.open('xb'); created=True; break
                except FileExistsError:
                    dest=base.with_name(f'{base.stem} ({index}){base.suffix}'); index+=1
            before=source.stat()
            with out,source.open('rb') as inp: shutil.copyfileobj(inp,out,1024*1024)
            after=source.stat()
            if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns) or digest(source)!=digest(dest): raise OSError('复制期间源文件变化或校验失败')
            shutil.copystat(source,dest)
            manifest.append([source.name,str(source),str(dest),before.st_size]); progress(f'已复制 {len(manifest)} 个文件')
        except OSError as e:
            if created: dest.unlink(missing_ok=True)
            failures.append(f'{source}: {e}')
    stamp=str(time.time_ns()); listing=target/f'整理清单-{stamp}.csv'
    with listing.open('x',newline='',encoding='utf-8-sig') as f:
        writer=csv.writer(f); writer.writerow(['文件名','原始路径','复制路径','字节数'])
        for row in manifest: writer.writerow(["'"+x if isinstance(x,str) and x.startswith(('=','+','-','@')) else x for x in row])
    return {'copied':len(manifest),'skipped':skipped,'failures':failures,'manifest':str(listing)}
