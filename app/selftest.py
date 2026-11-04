"""Packaged runtime diagnostic on synthetic data in an explicit data directory."""
import json
import time
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage,QColor
from app.core import export_files,digest,canonical
from app.version import __version__

def run(window,data):
    if window.store.accounts():raise ValueError('自检必须使用新的空数据目录，避免修改现有个人设置。')
    folder=data/f'selftest-{time.time_ns()}'
    source=folder/'wxid_demo'/'msg'/'file'/'2026-10';source.mkdir(parents=True)
    document=source/'公开示例.txt';document.write_text('Synthetic demo only.\n',encoding='utf-8')
    (source/'同内容副本.txt').write_bytes(document.read_bytes())
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
    duplicates=store.detect_duplicates(settle_seconds=0);assert store.duplicate_summary()['groups']==1
    assert store.detect_duplicates(settle_seconds=0)['cache_hits']==2
    assert store.bulk_manage('add_tags',tags='批量演示',filters={'query':'副本'})['success']==1
    from app.file_monitor import FileMonitor
    from app.statistics import storage_statistics
    monitor=FileMonitor(store,debounce=.1,max_wait=.3)
    try:
        assert monitor.start()
        deadline=time.monotonic()+10
        while '监控中' not in monitor.state and time.monotonic()<deadline:QApplication.processEvents();time.sleep(.02)
        assert '监控中' in monitor.state
        (source/'监控示例.txt').write_text('Synthetic monitor content.',encoding='utf-8')
        deadline=time.monotonic()+10
        while not store.search(query='监控示例') and time.monotonic()<deadline:QApplication.processEvents();time.sleep(.02)
        assert store.search(query='监控示例')
    finally:assert monitor.stop()
    assert storage_statistics(store)['count']==4
    window.table.selectRow(0);window.jump_to_directory();assert window.active_directory is not None
    assert window.active_directory['path']==canonical(source)
    window.directory_mode.setCurrentIndex(0)
    window.show_duplicates();assert not window.duplicate_dialog.model.checked_rows();window.duplicate_dialog.close()
    window.query.clear();window.reload();QApplication.processEvents()
    assert window.grab().save(str(data/'selftest.png'))
    report={'startup':True,'search':True,'annotations':True,'export':True,'source_unchanged':True,'backup_restore':True,'duplicates':True,'hash_cache':True,'monitor':True,'bulk':True,'statistics':True,'directory_views':True,'directory_details':True,'no_auto_duplicate_checks':True,'version':__version__}
    (data/'selftest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
