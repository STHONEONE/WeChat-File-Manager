import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtWidgets import QApplication
from app.main import Window
from app.ui.duplicates import DuplicatesDialog
from app.ui.statistics_view import StatisticsDialog
from tests.test_duplicates import dataset

def test_duplicate_and_statistics_views(tmp_path):
    app=QApplication.instance() or QApplication([]);store,folder,other=dataset(tmp_path);store.detect_duplicates(settle_seconds=0)
    window=Window(store,auto=False);window.show_duplicates();dialog=window.duplicate_dialog
    assert dialog.groups.topLevelItemCount()==3
    dialog.groups.setCurrentItem(dialog.groups.topLevelItem(0));app.processEvents()
    assert dialog.model.rowCount()==2
    dialog.members.selectRow(0);assert dialog.selected()[0]['path']
    window.statistics();assert window.statistics_dialog.accounts.topLevelItemCount()==2
    window.table.selectRow(0);window.note.setPlainText('未保存的编辑')
    (folder/'new.txt').write_bytes(b'demo');result=store.update_paths([folder/'new.txt'])
    window.monitor_updated({'kind':'events','result':result})
    assert window.is_dirty() and window.note.toPlainText()=='未保存的编辑'
    window.save_note();window.close()
