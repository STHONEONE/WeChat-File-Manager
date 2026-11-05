import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from app.main import Window
from app.ui.delete_dialog import DeleteDialog
from app.core import canonical
from tests.test_deletion import setup

def test_confirmation_requires_both_explicit_acknowledgements(tmp_path):
    app=QApplication.instance() or QApplication([]);store,root,p,backend,service=setup(tmp_path)
    dialog=DeleteDialog(service.prepare([p/'other.txt']))
    assert not dialog.confirm.isEnabled()
    dialog.selected_ack.setChecked(True);assert not dialog.confirm.isEnabled()
    dialog.original_ack.setChecked(True);assert dialog.confirm.isEnabled()
    dialog.reject();assert not backend.calls and (p/'other.txt').exists()

def test_directory_details_and_jump_keep_real_structure(tmp_path):
    app=QApplication.instance() or QApplication([]);store,root,p,backend,service=setup(tmp_path)
    before=sorted(str(path.relative_to(root)) for path in root.rglob('*'))
    window=Window(store,auto=False);window.table.selectRow(0);window.jump_to_directory()
    assert window.directory_mode.currentIndex()==1
    assert window.active_directory['path']==canonical(p)
    assert '真实路径' in window.dir_text.toPlainText() and window.detail_stack.currentIndex()==1
    window.directory_mode.setCurrentIndex(0);assert window.raw_directory_root.childCount()==1
    assert sorted(str(path.relative_to(root)) for path in root.rglob('*'))==before;window.close()

def test_window_background_confirmation_and_execution(tmp_path,monkeypatch):
    import time
    from PySide6.QtWidgets import QDialog
    app=QApplication.instance() or QApplication([]);store,root,p,backend,service=setup(tmp_path);window=Window(store,auto=False);window.delete_service=service
    def confirm(dialog):dialog.selected_ack.setChecked(True);dialog.original_ack.setChecked(True);return QDialog.DialogCode.Accepted
    monkeypatch.setattr(DeleteDialog,'exec',confirm)
    results=[];window.delete_done=lambda result:results.append(result)
    window.delete_paths([str(p/'other.txt')])
    deadline=time.monotonic()+8
    while not results and time.monotonic()<deadline:app.processEvents();time.sleep(.01)
    assert results and results[0]['result']['success']==1 and (p/'论文.pdf').exists() and not (p/'other.txt').exists()
    window.reload();window.refresh_deleted_counts([canonical(p/'other.txt')]);assert window.tree.topLevelItem(0).text(0)=='全部文件 (1)'
    deadline=time.monotonic()+3
    while window.worker.isRunning() and time.monotonic()<deadline:app.processEvents();time.sleep(.01)
    window.close()


def test_edit_selection_previews_only_checked_files(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    store,root,p,backend,service=setup(tmp_path)
    window=Window(store,auto=False)
    submitted=[]
    monkeypatch.setattr(window,'delete_paths',submitted.append)
    window.edit_selection_button.click()
    assert not window.recycle_checked_button.isEnabled()
    window.table.selectRow(0)
    assert not window.recycle_checked_button.isEnabled()
    index=window.proxy.index(1,0)
    assert window.proxy.setData(index,Qt.CheckState.Checked,Qt.ItemDataRole.CheckStateRole)
    window.recycle_checked_button.click()
    assert submitted==[[window.model.rows[1]['path']]]
    window.clear_checks_button.click()
    assert not window.recycle_checked_button.isEnabled()
    window.switch_page('search')
    assert not window.model.checkable
    window.close()
