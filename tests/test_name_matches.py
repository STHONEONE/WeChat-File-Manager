import os
import time
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPdfWriter
from PySide6.QtWidgets import QApplication, QDialog

from app.core import Store, canonical
from app.delete_service import DeleteService
from app.name_matches import name_groups
from app.snapshots import indexed_signature
from app.ui.delete_dialog import DeleteDialog
from app.ui.window import Window
from tests.test_deletion import FakeRecycle


def fixture(tmp_path):
    account = tmp_path / 'wxid_demo'
    folder = account / 'msg' / 'file'
    folder.mkdir(parents=True)
    store = Store(tmp_path / 'index.sqlite')
    store.add(account)
    return store, folder


def wait_for(app, predicate):
    deadline = time.monotonic() + 8
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert predicate()


def test_short_chinese_versions_and_cross_extension(tmp_path):
    store, folder = fixture(tmp_path)
    names = {'简历.docx', '简历（2）.pdf', '简历-最终版.docx'}
    for name in names | {'简历筛选评分标准汇总.docx'}:
        (folder / name).write_bytes(b'test')
    store.scan()
    groups, skipped = name_groups(store, lambda: False, lambda _: None)
    assert skipped == 0 and len(groups) == 1
    assert {row['name'] for row in groups[0]} == names


def test_sidebar_previews_and_only_checked_files_enter_recycle(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    store, folder = fixture(tmp_path)
    original = folder / '项目说明.txt'
    original.write_text('这是原版', encoding='utf-8')
    picture = folder / '项目说明-截图.png'
    image = QImage(24, 16, QImage.Format.Format_RGB32)
    image.fill(QColor('blue'))
    assert image.save(str(picture))
    pdf_path = folder / '项目说明-定稿.pdf'
    pdf = QPdfWriter(str(pdf_path))
    painter = QPainter(pdf)
    painter.drawText(100, 100, 'Preview demo')
    painter.end()
    del painter, pdf
    store.scan()
    service = DeleteService(store, FakeRecycle(tmp_path / 'recycle'), 0)
    window = Window(store, auto=False)
    window.delete_service = service
    window.show_duplicates()
    page = window.duplicate_dialog
    page.detect_button.click()
    wait_for(app, lambda: page.matches and not window.worker.isRunning())
    group = page.groups.topLevelItem(0)
    nodes = {group.child(i).text(0): group.child(i) for i in range(group.childCount())}
    page.groups.setCurrentItem(nodes[original.name])
    wait_for(app, lambda: page.text_preview.toPlainText() == '这是原版')
    assert page.path.toPlainText() == canonical(original)
    assert not page.checked
    page.groups.setCurrentItem(nodes[pdf_path.name])
    wait_for(app, lambda: page.preview_image is not None)
    page.groups.setCurrentItem(nodes[picture.name])
    wait_for(app, lambda: page.preview_image is not None)
    group.setCheckState(0,Qt.CheckState.Checked)
    assert len(page.checked)==3
    nodes[original.name].setCheckState(0,Qt.CheckState.Unchecked)
    nodes[pdf_path.name].setCheckState(0,Qt.CheckState.Unchecked)
    assert group.checkState(0)==Qt.CheckState.PartiallyChecked
    assert list(page.checked) == [canonical(picture)]
    results = []
    window.delete_done = results.append

    def confirm(dialog):
        assert [item.path for item in dialog.plan.items] == [canonical(picture)]
        assert dialog.plan.items[0].allowed
        assert dialog.confirm.isEnabled()
        dialog.confirm.click()
        return dialog.result()

    monkeypatch.setattr(DeleteDialog, 'exec', confirm)
    page.recycle_button.click()
    wait_for(app, lambda: results and not window.worker.isRunning())
    assert results[0]['result']['success'] == 1
    assert original.exists() and pdf_path.exists() and not picture.exists()
    window.close()


def test_changed_file_after_name_lookup_is_rejected(tmp_path):
    store, folder = fixture(tmp_path)
    original = folder / '项目说明.txt'
    original.write_bytes(b'initial')
    (folder / '项目说明-副本.txt').write_bytes(b'initial')
    store.scan()
    groups, _ = name_groups(store, lambda: False, lambda _: None)
    checked = next(row for row in groups[0] if row['path'] == canonical(original))
    original.write_bytes(b'replaced after checking')
    store.scan()
    service = DeleteService(store, FakeRecycle(tmp_path / 'recycle'), 0)
    plan = service.prepare([original], expected_snapshots={checked['path']: indexed_signature(checked)})
    assert not plan.items[0].allowed
    assert service.execute(plan, True, True)['skipped'] == 1
    assert original.read_bytes() == b'replaced after checking'


def test_group_checkbox_covers_unexpanded_and_paginated_members(tmp_path):
    app = QApplication.instance() or QApplication([])
    store, folder = fixture(tmp_path)
    rows = [dict(path=canonical(folder/f'项目说明-{i}.txt'),account=canonical(folder.parents[1]),
                 name=f'项目说明-{i}.txt',size=1) for i in range(155)]
    blocked = dict(rows[0], path=canonical(folder/'protected.dat'),name='protected.dat')
    window = Window(store,auto=False)
    window.show_duplicates()
    page = window.duplicate_dialog
    page.set_results([[rows[0],rows[1]],[*rows,blocked]],'演示')
    first,second=(page.groups.topLevelItem(i) for i in range(2))
    assert second.childCount()==0
    second.setCheckState(0,Qt.CheckState.Checked)
    assert len(page.checked)==155 and blocked['path'] not in page.checked
    assert first.checkState(0)==Qt.CheckState.Checked
    first.child(0).setCheckState(0,Qt.CheckState.Unchecked)
    assert second.checkState(0)==Qt.CheckState.PartiallyChecked
    second.setExpanded(True)
    page.load_members(second)
    assert second.child(154).checkState(0)==Qt.CheckState.Checked
    page.clear_selection()
    assert not page.checked and second.checkState(0)==Qt.CheckState.Unchecked
    window.close()
