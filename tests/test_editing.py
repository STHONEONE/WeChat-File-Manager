import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtWidgets import QApplication,QMessageBox
from app.main import Window
from tests.test_core import fixture

def test_unsaved_switch_cancel_and_save(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    store,root,p=fixture(tmp_path);(p/'第二份.pdf').write_bytes(b'other');store.scan()
    w=Window(store,auto=False);w.table.selectRow(0);app.processEvents()
    path=w.active['path'];w.note.setPlainText('未保存备注');assert w.is_dirty()
    monkeypatch.setattr(QMessageBox,'warning',lambda *a:QMessageBox.StandardButton.Cancel)
    w.table.selectRow(1);assert w.active['path']==path and w.note.toPlainText()=='未保存备注'
    w.reload();assert w.is_dirty()
    monkeypatch.setattr(QMessageBox,'warning',lambda *a:QMessageBox.StandardButton.Save)
    w.table.selectRow(1);assert w.active['path']!=path
    assert store.search(query='未保存备注')[0]['path']==path
    w.favorite.setChecked(True);selected=w.active['path'];assert w.save_note()
    assert w.active['path']==selected and not w.is_dirty()
    w.tags.setText('立即可见');assert w.save_note()
    tag_root=next(w.tree.topLevelItem(i) for i in range(w.tree.topLevelItemCount()) if (w.tree.topLevelItem(i).data(0,256) or {}).get('tags_view'))
    assert any('立即可见' in tag_root.child(i).text(0) for i in range(tag_root.childCount()))
    w.close()
