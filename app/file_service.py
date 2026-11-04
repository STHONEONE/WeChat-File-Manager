import csv
import hashlib
import shutil
import time
from pathlib import Path

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
