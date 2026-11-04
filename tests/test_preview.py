import os
import time
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage,QColor
from app.ui.preview import PreviewController
from app.ui.dialogs import DateFilter

def test_async_preview_and_date(tmp_path):
    app=QApplication.instance() or QApplication([])
    p=tmp_path/'demo.png';image=QImage(1200,800,QImage.Format.Format_RGB32);image.fill(QColor('green'));image.save(str(p))
    controller=PreviewController();received=[];controller.ready.connect(lambda img,msg:received.append((img,msg)))
    controller.request(str(p),p.stat().st_size)
    deadline=time.monotonic()+5
    while not received and time.monotonic()<deadline:app.processEvents();time.sleep(.01)
    assert received and received[0][1]=='' and received[0][0].width()<=640
    controller.request(str(p),100*1024**2);controller.clear()
    controller.pool.waitForDone();app.processEvents()
    assert len(received)==1  # Late responses after selection changes are ignored.
    date=DateFilter('日期');assert date.text()==''
    date.setText('2026-10-15');assert date.text()=='2026-10-15'
    date.clear();assert date.text()==''
