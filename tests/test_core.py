import os
from pathlib import Path
from app.core import Store, export_files, digest, canonical

def fixture(tmp_path):
    root=tmp_path/'xwechat_files'; p=root/'wxid_demo'/'msg'/'file'/'2026-10'; p.mkdir(parents=True)
    (p/'论文.pdf').write_bytes(b'paper')
    internal=root/'wxid_demo'/'db_storage'; internal.mkdir(); (internal/'message.db').write_bytes(b'private')
    cache=root/'wxid_demo'/'cache'; cache.mkdir(); (cache/'ignore.jpg').write_bytes(b'cache')
    store=Store(tmp_path/'data'/'index.sqlite'); store.add(root)
    return store,root,p

def test_scan_stats_and_metadata(tmp_path):
    store,root,p=fixture(tmp_path); result=store.scan(); assert result['files']==1
    r=store.search()[0]; assert r['month']=='2026-10'; assert r['category']=='文档'
    store.annotate(r['path'],'重要论文','科研,论文',True)
    store.alias(str(p).lower(),'十月资料')
    store.scan(); reopened=Store(store.path)
    assert len(reopened.search(query='重要',favorite=True,tag='科研'))==1
    assert any(d['alias']=='十月资料' for d in reopened.directories())
    assert next(d for d in store.directories() if d['path']==canonical(root/'wxid_demo'))['count']==3
    (p/'论文.pdf').unlink(); store.scan(); assert not store.search(); assert len(store.search(missing=True))==1

def test_copy_conflicts_protection_backup(tmp_path):
    store,root,p=fixture(tmp_path); store.scan(); rows=store.search(); before=digest(rows[0]['path'])
    target=tmp_path/'export'; a=export_files(rows,target,protected=[root]); b=export_files(rows,target,protected=[root]); c=export_files(rows,target,conflict='跳过',protected=[root])
    assert a['copied']==b['copied']==1 and c['skipped']==1
    assert digest(rows[0]['path'])==before
    assert len(list(target.rglob('*.pdf')))==2
    import pytest
    with pytest.raises(ValueError):export_files(rows,p,protected=[root])
    store.backup(tmp_path/'backup.sqlite'); assert Store(tmp_path/'backup.sqlite').search()==rows

def test_search_and_missing_account(tmp_path):
    store,root,p=fixture(tmp_path); store.scan()
    assert not store.search(minimum=100)
    assert len(store.search(start='2020-01-01',end='2099-01-01',directory=str(p)))==1
    old=root/'wxid_demo'; old.rename(root/'offline'); result=store.scan()
    assert result['errors'] and len(store.search())==1

def test_replacement_does_not_inherit_notes(tmp_path):
    store,root,p=fixture(tmp_path); store.scan(); r=store.search()[0]; store.annotate(r['path'],'private','tag',True)
    f=p/'论文.pdf'; f.rename(p/'old.pdf'); f.write_bytes(b'new content'); store.scan()
    assert store.search(query='论文.pdf')[0]['note']==''

def test_cancel_and_second_account(tmp_path):
    store,root,p=fixture(tmp_path); second=root/'wxid_second'/'FileStorage'/'File'; second.mkdir(parents=True); (second/'另一个.docx').write_bytes(b'doc')
    store.add(root); assert store.scan(cancelled=lambda:True)['cancelled']
    store.scan(); assert len(store.search())==2; assert len(store.accounts())==2

def test_stress(tmp_path):
    store,root,p=fixture(tmp_path)
    for i in range(10000):(p/f'文件-{i}.txt').touch()
    result=store.scan(); assert result['files']==10001; assert len(store.search(query='文件-'))==10000
