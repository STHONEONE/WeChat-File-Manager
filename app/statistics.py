"""Aggregate only metadata; internal directory totals retain full-scan timestamps."""
from app.duplicate_detector import VALID_JOIN

def storage_statistics(store):
    with store.connect() as db:
        total,size=db.execute('SELECT count(*),coalesce(sum(size),0) FROM files WHERE missing=0').fetchone()
        categories=[dict(r) for r in db.execute('SELECT category,count(*) count,sum(size) size FROM files WHERE missing=0 GROUP BY category ORDER BY size DESC')]
        accounts=[dict(r) for r in db.execute('''SELECT a.name,a.path,count(f.path) count,coalesce(sum(f.size),0) size,
            s.scanned_at,s.complete,s.error FROM accounts a LEFT JOIN files f ON f.account=a.path AND f.missing=0
            LEFT JOIN account_scan_state s ON s.account=a.path GROUP BY a.path ORDER BY size DESC''')]
        largest=[dict(r) for r in db.execute('''SELECT f.*,a.name account_name FROM files f JOIN accounts a ON a.path=f.account
            WHERE missing=0 ORDER BY size DESC,f.path LIMIT 100''')]
        directories=[dict(r) for r in db.execute('''SELECT d.*,a.name account_name FROM directories d JOIN accounts a ON a.path=d.account
            WHERE d.parent=d.account ORDER BY d.size DESC LIMIT 100''')]
        verified=db.execute('SELECT count(*)'+VALID_JOIN).fetchone()[0]
    return {'count':total,'size':size,'categories':categories,'accounts':accounts,'largest':largest,'directories':directories,
            'duplicates':store.duplicate_summary(),'verified':verified,'scan':store.setting('state:scan',{}),'last_event':store.setting('state:event-time',None),'monitor':store.setting('state:monitor',{})}
