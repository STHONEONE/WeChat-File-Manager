import json
import os
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QAbstractTableModel, QModelIndex, QSortFilterProxyModel, QIdentityProxyModel, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QImageReader, QPixmap, QIcon, QPainter, QColor, QFontDatabase, QFont
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QLineEdit,QComboBox,QPushButton,QSplitter,QTreeWidget,QTreeWidgetItem,QTableView,QLabel,QTextEdit,QCheckBox,QFormLayout,QFileDialog,QMessageBox,QInputDialog,QMenu,QDoubleSpinBox,QDialog,QDialogButtonBox,QProgressBar)
from app.core import Store, CATEGORIES, LABELS, candidates, canonical, human, export_files

from app.ui.window import Window, Worker
from app.ui.file_model import FilesModel
from app.version import __version__

def main():
    app=QApplication(sys.argv); app.setApplicationName('WeChatFileManager'); app.setStyle('Fusion')
    asset_base=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1])); app.setWindowIcon(QIcon(str(asset_base/'assets'/'app.ico')))
    app.setStyleSheet('QWidget {font-family:"Microsoft YaHei UI";font-size:13px;} QMainWindow {background:#f5f7fa;} QLabel#title {font-size:26px;font-weight:600;color:#143b32;} QLabel#caption {color:#687a74;margin-bottom:10px;} QPushButton {padding:7px 12px;border:1px solid #cbd8d2;border-radius:5px;background:white;} QPushButton:hover {background:#e3f4ec;} QLineEdit,QComboBox,QDoubleSpinBox,QTextEdit {padding:6px;border:1px solid #d3ded8;border-radius:4px;background:white;} QTreeWidget,QTableView {border:1px solid #dce5df;background:white;selection-background-color:#c6ead8;selection-color:#123d30;} QHeaderView::section {padding:8px;background:#eaf1ed;border:0;}')
    data=Path(os.environ.get('WFM_DATA_DIR',str(Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'WeChatFileManager')))
    if '--self-test' in sys.argv and not os.environ.get('WFM_DATA_DIR'):
        raise SystemExit('Self-test requires an explicit empty WFM_DATA_DIR.')
    smoke='--smoke-test' in sys.argv or '--self-test' in sys.argv
    store=Store(data/'index.sqlite'); window=Window(store,auto=not smoke); window.show()
    if smoke:
        def finish():
            if '--self-test' in sys.argv:
                try:
                    from app.selftest import run
                    run(window,data)
                except Exception as e:
                    (data/'selftest-error.txt').write_text(str(e),encoding='utf-8');app.exit(1);return
            window.grab().save(str(data/'smoke.png'))
            (data/'smoke.json').write_text(json.dumps({'rows':window.model.rowCount(),'qt_window_created':True}),encoding='utf-8')
            window.close(); app.quit()
        QTimer.singleShot(1000,finish)
    sys.exit(app.exec())

if __name__=='__main__':main()
