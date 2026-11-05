import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication,QDialog
from app.main import Window
from app.ui.delete_dialog import DeleteDialog
from app.core import canonical
from tests.test_deletion import setup

def test_confirmation_is_one_click_and_requires_a_checked_item(tmp_path):
    app=QApplication.instance() or QApplication([]);store,root,p,backend,service=setup(tmp_path)
    dialog=DeleteDialog(service.prepare([p/'other.txt']))
    assert dialog.confirm.isEnabled() and not dialog.confirm.isDefault()
    model=dialog.preview_model;index=model.index(0,0)
    model.setData(index,Qt.CheckState.Unchecked,Qt.ItemDataRole.CheckStateRole)
    assert not dialog.confirm.isEnabled()
    model.setData(index,Qt.CheckState.Checked,Qt.ItemDataRole.CheckStateRole)
    dialog.confirm.click()
    assert dialog.result()==QDialog.DialogCode.Accepted
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
    def confirm(dialog):
        dialog.confirm.click()
        return dialog.result()
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


def test_completion_shows_short_success_or_failure_details(tmp_path,monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    app=QApplication.instance() or QApplication([]);store,root,p,backend,service=setup(tmp_path)
    window=Window(store,auto=False)
    dialogs=[]
    notices=[]
    monkeypatch.setattr(QMessageBox,'information',lambda parent,title,message:notices.append((title,message)))
    monkeypatch.setattr(QDialog,'exec',lambda dialog:dialogs.append(dialog.windowTitle()))
    excluded=canonical(p/'论文.pdf')
    first=service.execute(service.prepare([p/'other.txt',excluded]),True,True,excluded={excluded})
    window.delete_done({'result':first})
    assert '已移入回收站 1 个文件' in window.progress_label.text()
    assert notices==[('清理完成','已移入回收站 1 个文件')]
    assert not dialogs and (p/'论文.pdf').exists()
    backend.fail.add('论文.pdf')
    failed=service.execute(service.prepare([excluded]),True,True)
    window.delete_done({'result':failed})
    assert dialogs==['有文件未能确认回收'] and (p/'论文.pdf').exists()
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
