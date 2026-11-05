import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtWidgets import QApplication
from app.main import Window
from app.ui.statistics_view import StatisticsDialog
from tests.test_duplicates import dataset

def test_statistics_view_and_pending_edit(tmp_path):
    app=QApplication.instance() or QApplication([]);store,folder,other=dataset(tmp_path);store.detect_duplicates(settle_seconds=0)
    window=Window(store,auto=False)
    window.statistics();assert window.statistics_dialog.accounts.topLevelItemCount()==2
    window.table.selectRow(0);window.note.setPlainText('未保存的编辑')
    (folder/'new.txt').write_bytes(b'demo');result=store.update_paths([folder/'new.txt'])
    window.monitor_updated({'kind':'events','result':result})
    assert window.is_dirty() and window.note.toPlainText()=='未保存的编辑'
    window.save_note();window.close()
