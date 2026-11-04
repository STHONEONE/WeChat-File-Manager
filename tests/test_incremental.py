from tests.test_duplicates import dataset
from tests.test_core import fixture
from app.core import canonical

def test_metadata_diff_reuses_hash_and_preserves_annotations(tmp_path):
    store,folder,other=dataset(tmp_path);store.detect_duplicates(settle_seconds=0)
    path=canonical(folder/'a.txt');store.annotate(path,'保留备注','科研',True)
    repeat=store.scan();assert repeat['changed']==0 and repeat['unchanged']==7 and repeat['directory_updates']==0
    assert store.detect_duplicates(settle_seconds=0)['cache_hits']==7
    (folder/'a.txt').write_bytes(b'other');result=store.update_paths([folder/'a.txt'])
    assert result['changed']==1 and store.search(query='保留备注')[0]['favorite']==1
    assert store.duplicate_summary()['groups']==2
    (folder/'new.txt').write_bytes(b'new');assert store.update_paths([folder/'new.txt'])['changed']==1
    (folder/'new.txt').unlink();assert store.update_paths([folder/'new.txt'])['deleted']==1
    assert len(store.search(missing=True))==1
    assert store.directory_info(folder)['count']==4

def test_upgrade_from_v11_makes_backup_and_keeps_settings(tmp_path):
    import sqlite3
    from app.database import SCHEMA
    from app.core import Store
    p=tmp_path/'v11.sqlite';root=canonical(tmp_path/'account')
    with sqlite3.connect(p) as db:
        db.executescript(SCHEMA)
        db.execute('ALTER TABLE directories ADD COLUMN parent TEXT');db.execute('CREATE TABLE tag_catalog(name TEXT PRIMARY KEY)')
        db.execute('INSERT INTO accounts VALUES (?,?,?)',(root,'旧账号','账号备注'))
        db.execute('INSERT INTO files(path,account,name,category,size,mtime,note,tags,favorite) VALUES (?,?,?,?,?,?,?,?,?)',(root+'\\file.txt',root,'file.txt','文档',1,1700000000,'旧备注','标签',1))
        db.execute("INSERT INTO settings VALUES ('monitor:enabled','true')");db.execute('PRAGMA user_version=3')
    store=Store(p)
    assert store.search()[0]['note']=='旧备注';assert store.setting('monitor:enabled') is True
    backups=list((tmp_path/'backups').glob('before-upgrade-*.sqlite'));assert len(backups)==1
    with sqlite3.connect(backups[0]) as db:assert db.execute('PRAGMA user_version').fetchone()[0]==3

def test_unreachable_event_keeps_old_metadata(tmp_path):
    store,root,p=fixture(tmp_path);store.scan();path=canonical(p/'论文.pdf');store.annotate(path,'keep','tag',True)
    p.rename(p.parent/'offline')
    result=store.update_paths([path]);assert result['errors']
    assert store.search()[0]['note']=='keep' and not store.search()[0]['missing']

def test_cancel_rolls_back_in_progress_account_transaction(tmp_path):
    store,root,p=fixture(tmp_path)
    for i in range(300):(p/f'{i}.txt').write_bytes(b'demo')
    committing=False;calls=0
    def progress(text):
        nonlocal committing
        if text.startswith('提交账号索引'):committing=True
    def cancelled():
        nonlocal calls
        if committing:calls+=1
        return calls>2
    result=store.scan(progress,cancelled)
    assert result['cancelled'] and not store.search()

def test_file_permission_failure_does_not_mark_deleted(tmp_path,monkeypatch):
    import os
    store,root,p=fixture(tmp_path);store.scan();path=canonical(p/'论文.pdf');store.annotate(path,'权限失败也保留','标签',True)
    original=os.lstat
    def denied(target,*args,**kwargs):
        if canonical(target)==path:raise PermissionError('simulated denied metadata access')
        return original(target,*args,**kwargs)
    monkeypatch.setattr(os,'lstat',denied)
    result=store.scan();assert result['errors']
    assert store.search()[0]['note']=='权限失败也保留' and not store.search()[0]['missing']
