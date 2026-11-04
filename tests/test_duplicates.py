import time
from pathlib import Path
from app.core import Store,digest
from app import duplicate_detector

def dataset(tmp_path):
    root=tmp_path/'xwechat_files';folder=root/'wxid_demo'/'msg'/'file';folder.mkdir(parents=True)
    other=root/'wxid_second'/'msg'/'file';other.mkdir(parents=True)
    (folder/'a.txt').write_bytes(b'alpha');(other/'different-name.txt').write_bytes(b'alpha')
    (folder/'not-duplicate.txt').write_bytes(b'gamma')
    (folder/'empty.txt').touch();(other/'empty2.txt').touch()
    (folder/'large.bin').write_bytes(b'x'*(2*1024*1024));(other/'large-copy.bin').write_bytes(b'x'*(2*1024*1024))
    store=Store(tmp_path/'data'/'index.sqlite');store.add(root);store.scan()
    return store,folder,other

def test_duplicates_and_cached_recheck(tmp_path):
    store,folder,other=dataset(tmp_path);before=digest(folder/'a.txt')
    first=store.detect_duplicates(settle_seconds=0)
    assert first['hashed']==7 and first['complete']
    groups=store.duplicate_groups();assert len(groups)==3
    assert store.duplicate_summary()['redundant']==2*1024*1024+5
    assert len(store.duplicate_groups(cross_account=True))==3
    members=store.duplicate_members(groups[0]['sha256'],groups[0]['size']);assert len(members)==2
    second=store.detect_duplicates(settle_seconds=0)
    assert second['hashed']==0 and second['cache_hits']==7 and second['cache_hit_rate']==1
    (other/'different-name.txt').write_bytes(b'delta');store.scan()
    assert len(store.duplicate_groups())==2
    third=store.detect_duplicates(settle_seconds=0)
    assert third['hashed']==1 and third['cache_hits']==6
    assert digest(folder/'a.txt')==before

def test_changing_file_never_persists_valid_hash(tmp_path,monkeypatch):
    store,folder,other=dataset(tmp_path)
    original=duplicate_detector.hash_stream
    def change(path,cancelled):
        value=original(path,cancelled)
        if Path(path).name=='a.txt':Path(path).write_bytes(b'changed while reading')
        return value
    monkeypatch.setattr(duplicate_detector,'hash_stream',change)
    result=store.detect_duplicates(settle_seconds=0)
    assert result['skipped']==1 and not result['complete']
    with store.connect() as db:assert not db.execute('SELECT 1 FROM hash_cache WHERE path=? AND valid=1',(str(folder/'a.txt').lower(),)).fetchone()

def test_hash_cancel_and_missing_cache_invalidation(tmp_path):
    store,folder,other=dataset(tmp_path)
    assert store.detect_duplicates(cancelled=lambda:True,settle_seconds=0)['cancelled']
    store.detect_duplicates(settle_seconds=0)
    (other/'large-copy.bin').unlink();store.scan()
    assert len(store.duplicate_groups())==2

def test_recent_file_is_delayed(tmp_path):
    store,folder,other=dataset(tmp_path)
    result=store.detect_duplicates(settle_seconds=60)
    assert result['skipped']==7 and result['hashed']==0 and not result['complete']

def test_stale_index_does_not_reuse_cache(tmp_path):
    store,folder,other=dataset(tmp_path);store.detect_duplicates(settle_seconds=0)
    (folder/'a.txt').write_bytes(b'other')
    result=store.detect_duplicates(settle_seconds=0)
    assert result['skipped']==1 and not result['complete']
    assert store.duplicate_summary()['groups']==2

def test_unique_size_never_reads_content_and_stream_can_cancel(tmp_path):
    import pytest
    store,folder,other=dataset(tmp_path);(folder/'unique.bin').write_bytes(b'u'*123);store.scan()
    assert store.detect_duplicates(settle_seconds=0)['hashed']==7
    calls=0
    def cancel():
        nonlocal calls
        calls+=1;return calls>=2
    with pytest.raises(duplicate_detector.HashCancelled):duplicate_detector.hash_stream(folder/'large.bin',cancel)
