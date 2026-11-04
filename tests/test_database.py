import sqlite3
import pytest
from app.core import Store
from app.database import SCHEMA_VERSION
from tests.test_core import fixture

def test_migrate_v10_and_restore_all_metadata(tmp_path):
    store, root, folder = fixture(tmp_path)
    store.scan(); row = store.search()[0]
    store.annotate(row['path'], '升级保留备注', '科研,论文', True)
    store.alias(str(folder).lower(), '中文目录')
    store.rename(store.accounts()[0]['path'], '我的账号', '账号备注')
    with store.connect() as db: db.execute('PRAGMA user_version=0')
    old = tmp_path/'v10.sqlite'; store.backup(old)
    store = Store(store.path)
    with store.connect() as db: assert db.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION
    store.annotate(row['path'], 'changed', '', False)
    rollback = store.restore(old)
    assert Store(rollback).search()[0]['note'] == 'changed'
    assert store.search(favorite=True)[0]['note'] == '升级保留备注'
    assert store.accounts()[0]['note'] == '账号备注'
    assert any(d['alias']=='中文目录' for d in store.directories())
    assert store.source_roots()

def test_reject_invalid_without_touching_current(tmp_path):
    store, root, folder = fixture(tmp_path); store.scan()
    before=store.search()
    invalid=tmp_path/'invalid.sqlite';invalid.write_bytes(b'not sqlite')
    with pytest.raises((ValueError,sqlite3.DatabaseError)):store.restore(invalid)
    empty=tmp_path/'empty.sqlite'
    with sqlite3.connect(empty):pass
    with pytest.raises(ValueError):store.restore(empty)
    assert store.search()==before

def test_restore_committed_wal(tmp_path):
    store,root,folder=fixture(tmp_path);store.scan()
    source=tmp_path/'wal.sqlite';store.backup(source)
    with sqlite3.connect(source) as external:
        external.execute('PRAGMA journal_mode=WAL')
        external.execute("UPDATE files SET note='WAL 中的备注'");external.commit()
        assert Path(str(source)+'-wal').exists()
        store.restore(source)
    assert store.search()[0]['note']=='WAL 中的备注'

from pathlib import Path
