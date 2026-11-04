import os
import sqlite3
import time
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication,QMessageBox
from app.core import Store,canonical
from app.database import SCHEMA,SCHEMA_VERSION
from app.main import Window
from tests.test_core import fixture
from tests.test_search import populate

def test_original_v10_schema_migration(tmp_path):
    dbpath=tmp_path/'v10.sqlite';root=canonical(tmp_path/'account');path=root+os.sep+'原文件.pdf'
    with sqlite3.connect(dbpath) as db:
        db.executescript(SCHEMA)
        db.execute('INSERT INTO accounts VALUES (?,?,?)',(root,'原账号','账号备注'))
        db.execute('INSERT INTO files(path,account,name,category,size,mtime,month,identity,seen,note,tags,favorite) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(path,root,'原文件.pdf','文档',1,1700000000,'2026-10','id','seen','旧版备注','原标签',1))
        db.execute('INSERT INTO directories VALUES (?,?,?,?,?)',(root,root,'旧别名',1,1))
    store=Store(dbpath)
    assert store.search(favorite=True)[0]['note']=='旧版备注'
    assert store.tags()['原标签']==1
    assert store.directory_info(root)['alias']=='旧别名'
    with store.connect() as db:assert db.execute('PRAGMA user_version').fetchone()[0]==SCHEMA_VERSION

def test_future_backup_rejected(tmp_path):
    store,root,p=fixture(tmp_path);store.scan();before=store.search();dest=tmp_path/'future.sqlite';store.backup(dest)
    with sqlite3.connect(dest) as db:db.execute('PRAGMA user_version=999')
    import pytest
    with pytest.raises(ValueError):store.restore(dest)
    assert store.search()==before

def test_backup_refuses_source_directory(tmp_path):
    import pytest
    store,root,p=fixture(tmp_path)
    with pytest.raises(ValueError):store.backup(p/'do-not-write.sqlite')
    assert not (p/'do-not-write.sqlite').exists()

def test_discard_refresh_and_cancel_close(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]);store,root,p=fixture(tmp_path);store.scan();w=Window(store,auto=False)
    w.table.selectRow(0);w.note.setPlainText('丢弃此修改')
    monkeypatch.setattr(QMessageBox,'warning',lambda *a:QMessageBox.StandardButton.Discard)
    w.reload();assert not w.is_dirty();assert store.search()[0]['note']==''
    w.table.selectRow(0);w.tags.setText('未保存标签')
    monkeypatch.setattr(QMessageBox,'warning',lambda *a:QMessageBox.StandardButton.Cancel)
    w.show();assert not w.close();assert w.is_dirty()
    monkeypatch.setattr(QMessageBox,'warning',lambda *a:QMessageBox.StandardButton.Save)
    assert w.close();assert store.search()[0]['tags']=='未保存标签'

def test_window_initial_rows_bounded_and_sort_global(tmp_path):
    app=QApplication.instance() or QApplication([]);store=Store(tmp_path/'index.sqlite');populate(store)
    begin=time.perf_counter();w=Window(store,auto=False);elapsed=time.perf_counter()-begin
    assert w.model.rowCount()==200 and w.model.total==50000 and elapsed<5
    w.sort_changed(2,Qt.SortOrder.AscendingOrder)
    assert w.model.rows[0]['size']==0
    w.model.fetchMore();assert w.model.rows[200]['size']==200
    w.close()

def test_scan_cancels_within_one_large_directory(tmp_path):
    store,root,p=fixture(tmp_path)
    for i in range(100):(p/f'{i}.txt').touch()
    calls=0
    def cancelled():
        nonlocal calls
        calls+=1
        return calls>25
    assert store.scan(cancelled=cancelled)['cancelled']
    assert not store.search()  # No partial account transaction is committed.
