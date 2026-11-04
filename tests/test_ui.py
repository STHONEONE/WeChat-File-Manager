import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtWidgets import QApplication
from app.core import Store
from app.main import Window

def test_ui(tmp_path):
    app=QApplication.instance() or QApplication([])
    root=tmp_path/'wxid_test'; (root/'msg'/'file').mkdir(parents=True); (root/'msg'/'file'/'测试.pdf').write_bytes(b'pdf')
    store=Store(tmp_path/'index.sqlite'); store.add(root); store.scan()
    window=Window(store,auto=False); window.show(); app.processEvents()
    assert window.model.rowCount()==1
    window.table.selectRow(0); app.processEvents(); assert window.active['name']=='测试.pdf'
    window.note.setPlainText('论文备注'); window.tags.setText('科研'); window.favorite.setChecked(True); window.save_note()
    assert store.search(favorite=True,tag='科研')[0]['note']=='论文备注'
    window.switch_page('search'); window.query.setText('不存在'); window.reload(); assert window.model.rowCount()==0
    window.query.clear(); window.reload(); window.grab().save(str(tmp_path/'ui.png')); window.close()
