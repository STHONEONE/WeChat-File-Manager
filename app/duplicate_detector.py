"""Size-filtered, serial SHA-256 verification. Source files are always read-only."""
import hashlib
import time
from pathlib import Path
from app.snapshots import signature,indexed_signature,safe_parent
from app.paths import linked

class HashCancelled(Exception):pass

def hash_stream(path,cancelled):
    h=hashlib.sha256()
    with open(path,'rb') as stream:
        while True:
            if cancelled():raise HashCancelled()
            block=stream.read(1024*1024)
            if not block:break
            h.update(block)
    return h.hexdigest()

VALID_JOIN=''' FROM files f JOIN hash_cache h ON h.path=f.path
    WHERE f.missing=0 AND h.valid=1 AND h.size=f.size AND h.mtime_ns=f.mtime_ns
    AND h.ctime_ns=f.ctime_ns AND h.identity=f.identity'''

class DuplicateMixin:
    def detect_duplicates(self,progress=lambda text:None,cancelled=lambda:False,settle_seconds=1.0):
        started=time.monotonic();now=time.time();last_progress=0.
        with self.connect() as db:
            rows=[dict(r) for r in db.execute('''SELECT f.* FROM files f WHERE missing=0 AND size IN
                (SELECT size FROM files WHERE missing=0 GROUP BY size HAVING count(*)>1) ORDER BY size,path''')]
        result={'candidates':len(rows),'hashed':0,'cache_hits':0,'skipped':0,'errors':[],'cancelled':False,'complete':False}
        self.set_setting('state:duplicates',dict(result,time=now,running=True))
        for row in rows:
            if cancelled():result['cancelled']=True;break
            p=Path(row['path'])
            try:
                if not safe_parent(p,row['account']) or linked(p):raise OSError('文件不可访问或经过链接')
                before=p.stat();sig=signature(before)
                if sig!=indexed_signature(row):raise OSError('元数据已变化，请等待监控更新或刷新索引')
                if time.time()-max(before.st_mtime,before.st_ctime)<settle_seconds:raise OSError('文件刚刚变化，延迟检测')
                with self.connect() as db:cached=db.execute('SELECT * FROM hash_cache WHERE path=?',(row['path'],)).fetchone()
                if cached and cached['valid'] and indexed_signature(cached)==sig:
                    if signature(p.stat())!=sig:raise OSError('复用缓存时文件变化，已跳过')
                    result['cache_hits']+=1
                else:
                    value=hash_stream(p,cancelled)
                    if signature(p.stat())!=sig:raise OSError('内容读取期间文件变化，已跳过')
                    with self.connect() as db:
                        current=db.execute('SELECT * FROM files WHERE path=? AND missing=0',(row['path'],)).fetchone()
                        if not current or indexed_signature(current)!=sig or signature(p.stat())!=sig:
                            raise OSError('索引或文件在校验期间变化，已跳过')
                        db.execute('''INSERT OR REPLACE INTO hash_cache(path,size,mtime_ns,ctime_ns,identity,sha256,verified_at,valid)
                            VALUES (?,?,?,?,?,?,?,1)''',(row['path'],*sig,value,time.time()))
                    result['hashed']+=1
            except HashCancelled:result['cancelled']=True;break
            except OSError as e:
                with self.connect() as db:db.execute('UPDATE hash_cache SET valid=0 WHERE path=?',(row['path'],))
                result['skipped']+=1;result['errors'].append(f'{p}: {e}')
            tick=time.monotonic()
            if tick-last_progress>=.15:
                progress(f'重复检测：{result["hashed"]+result["cache_hits"]+result["skipped"]:,}/{len(rows):,}；缓存命中 {result["cache_hits"]:,}')
                last_progress=tick
        result['complete']=not result['cancelled'] and not result['skipped']
        result['seconds']=round(time.monotonic()-started,4)
        result['cache_hit_rate']=result['cache_hits']/max(result['hashed']+result['cache_hits'],1)
        self.set_setting('state:duplicates',dict(result,time=time.time(),running=False))
        return result

    def duplicate_groups(self,order='redundant',cross_account=False,limit=200,offset=0):
        if order not in {'redundant','count','total'}:raise ValueError('未知重复组排序')
        if not 1<=limit<=1000 or offset<0:raise ValueError('分页范围无效')
        sql='''SELECT h.sha256,f.size,count(*) AS count,count(DISTINCT f.account) AS accounts,
               f.size*count(*) AS total,f.size*(count(*)-1) AS redundant,min(h.verified_at) AS verified_at'''+VALID_JOIN+''' GROUP BY h.sha256,f.size HAVING count(*)>1'''
        if cross_account:sql+=' AND count(DISTINCT f.account)>1'
        sql+=' ORDER BY '+('count' if order=='count' else 'total' if order=='total' else 'redundant')+' DESC,h.sha256 LIMIT ? OFFSET ?'
        with self.connect() as db:return [dict(r) for r in db.execute(sql,(limit,offset))]

    def duplicate_members(self,sha256,size,limit=200,offset=0):
        if not 1<=limit<=1000 or offset<0:raise ValueError('分页范围无效')
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT f.*,(SELECT name FROM accounts a WHERE a.path=f.account) account_name'+VALID_JOIN+' AND h.sha256=? AND f.size=? ORDER BY f.path LIMIT ? OFFSET ?',(sha256,size,limit,offset))]

    def duplicate_summary(self):
        sql='SELECT count(*),coalesce(sum(n),0),coalesce(sum(size*(n-1)),0) FROM (SELECT f.size,count(*) n'+VALID_JOIN+' GROUP BY h.sha256,f.size HAVING count(*)>1)'
        with self.connect() as db:groups,files,redundant=db.execute(sql).fetchone()
        return {'groups':groups,'files':files,'redundant':redundant,'state':self.setting('state:duplicates',{})}
