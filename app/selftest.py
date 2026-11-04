"""Packaged runtime diagnostic on synthetic data in an explicit data directory."""
import json
import time
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage,QColor
from app.core import export_files,digest

def run(window,data):
    if window.store.accounts():raise ValueError('自检必须使用新的空数据目录，避免修改现有个人设置。')
    folder=data/f'selftest-{time.time_ns()}'
    source=folder/'wxid_demo'/'msg'/'file'/'2026-10';source.mkdir(parents=True)
    document=source/'公开示例.txt';document.write_text('Synthetic demo only.\n',encoding='utf-8')
    image=QImage(480,320,QImage.Format.Format_RGB32);image.fill(QColor('#16865b'));image.save(str(source/'示例图片.png'))
    store=window.store;store.add(source.parents[2]);store.scan()
    store.rename(store.accounts()[0]['path'],'演示账号（虚构）','')
    window.update_accounts();window.rebuild_tree();window.query.setText('公开示例');window.reload()
    assert window.model.rowCount()==1
    window.table.selectRow(0);QApplication.processEvents();window.note.setPlainText('演示备注');window.tags.setText('演示');window.favorite.setChecked(True);assert window.save_note()
    before=digest(document);result=export_files(window.selected(),folder/'export',protected=[source.parents[2]])
    assert result['copied']==1 and digest(document)==before
    backup=folder/'backup.sqlite';store.backup(backup);store.annotate(window.active['path'],'changed','',False);store.restore(backup)
    assert store.search(query='演示备注',favorite=True)
    window.query.clear();window.reload();QApplication.processEvents()
    assert window.grab().save(str(data/'selftest.png'))
    report={'startup':True,'search':True,'annotations':True,'export':True,'source_unchanged':True,'backup_restore':True,'version':'1.1.0'}
    (data/'selftest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
