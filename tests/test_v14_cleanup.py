import os
import time
from pathlib import Path

import pytest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication,QDialog

from app.cleanup_selection import build_selection
from app.core import Store, canonical
from app.delete_service import DeleteService
from app.duplicate_detector import HashCancelled
from app.ui.delete_dialog import DeleteDialog
from app.ui.window import Window
from tests.test_deletion import FakeRecycle


def build_fixture(tmp_path, groups, copies=2, large_group=0):
    root = tmp_path / 'xwechat_files'
    first = root / 'wxid_first' / 'msg' / 'file'
    second = root / 'wxid_second' / 'msg' / 'file'
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    for index in range(groups):
        for copy in range(large_group if index == 0 and large_group else copies):
            folder = first if copy == 0 else second
            (folder / f'group-{index:03d}-{copy:03d}.txt').write_bytes(f'{index:04d}'.encode())
    store = Store(tmp_path / 'data' / 'index.sqlite')
    store.add(root)
    store.scan()
    assert store.detect_duplicates(settle_seconds=0)['complete']
    backend = FakeRecycle(tmp_path / 'mock-recycle')
    return store, first, second, DeleteService(store, backend, 0)


def test_global_suggestions_span_both_paginated_lists(tmp_path):
    app = QApplication.instance() or QApplication([])
    store, first, second, service = build_fixture(tmp_path, 201, large_group=202)
    preferred = canonical(second / 'group-000-201.txt')
    store.annotate(preferred, '保留这份', '', True)
    window = Window(store, auto=False)
    window.delete_service = service
    window.show_duplicates()
    page = window.duplicate_dialog
    draft = build_selection(service, lambda: False, lambda _: None)
    page.apply_suggestions(draft)
    assert page.groups.topLevelItemCount() == 200
    assert len(draft.keepers) == 201 and len(page.checked) == 401
    assert sum(row['size'] for row in page.checked.values()) == 1604
    assert preferred not in page.checked
    page.groups.setCurrentItem(page.groups.topLevelItem(0))
    group = page.group_key()
    assert draft.keepers[group] == preferred and len(page.model.rows) == 200
    page.load_members()
    assert len(page.model.rows) == 202 and len(page.model.checked_rows()) == 201
    page.members.selectRow(0)
    new_keeper = page.selected()[0]['path']
    page.set_keeper()
    assert draft.keepers[group] == new_keeper and preferred in page.checked
    page.load_groups()
    page.groups.setCurrentItem(page.groups.topLevelItem(200))
    page.model.setData(page.model.index(1, 0), Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    window.switch_page('search')
    window.show_duplicates()
    assert len(page.checked) == 400 and page.groups.currentItem() == page.groups.topLevelItem(200)
    assert not page.model.checked_rows()
    page.clear_selection()
    assert not page.checked and not page.recycle.isEnabled()
    window.close()


def test_preview_cancellation_and_exact_execution_subset(tmp_path):
    app = QApplication.instance() or QApplication([])
    store, first, second, service = build_fixture(tmp_path, 2, copies=3)
    draft = build_selection(service, lambda: False, lambda _: None)
    selected = list(draft.suggestions())
    plan = service.prepare(selected, duplicate=True, selection=draft)
    assert all(item.allowed and item.keeper.path not in selected for item in plan.items)
    dialog = DeleteDialog(plan)
    preview = dialog.preview_model
    preview.setData(preview.index(0, 0), Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    assert preview.count == 3 and preview.size == 12
    service.backend.fail.add(Path(selected[1]).name)
    result = service.execute(plan, True, True, excluded=dialog.excluded_paths())
    assert result['success'] == 2 and result['failed'] == result['skipped'] == 1
    assert service.backend.calls == selected[2:]
    assert all(Path(path).is_file() for path in [selected[0], selected[1], *draft.keepers.values()])


@pytest.mark.parametrize('changed_file', ['selected', 'keeper'])
def test_external_change_invalidates_guarded_recycle(tmp_path, changed_file):
    store, first, second, service = build_fixture(tmp_path, 1)
    draft = build_selection(service, lambda: False, lambda _: None)
    selected = next(iter(draft.suggestions()))
    plan = service.prepare([selected], duplicate=True, selection=draft)
    path = selected if changed_file == 'selected' else plan.items[0].keeper.path
    Path(path).write_bytes(b'changed after preview')
    assert service.execute(plan, True, True)['skipped'] == 1
    assert not service.backend.calls


def test_incomplete_cancelled_and_unavailable_suggestions(tmp_path):
    store, first, second, service = build_fixture(tmp_path, 1)
    with pytest.raises(HashCancelled):
        build_selection(service, lambda: True, lambda _: None)
    def unavailable(path):
        raise OSError('回收站不可用')
    service.backend.supports = unavailable
    draft = build_selection(service, lambda: False, lambda _: None)
    assert not draft.suggestions() and len(draft.blocked) == 2
    store.set_setting('state:duplicates', {'complete': False})
    with pytest.raises(ValueError, match='完成重复文件检测'):
        build_selection(service, lambda: False, lambda _: None)


def test_duplicate_page_buttons_use_background_preview_and_confirm(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    store,first,second,service=build_fixture(tmp_path,2,copies=3)
    window=Window(store,auto=False)
    window.delete_service=service
    window.show_duplicates()
    page=window.duplicate_dialog
    results=[]
    window.delete_done=results.append

    def wait_for(predicate):
        deadline=time.monotonic()+8
        while not predicate() and time.monotonic()<deadline:
            app.processEvents()
            time.sleep(.01)
        assert predicate()

    def confirm(dialog):
        assert dialog.preview_model.count==4
        index=dialog.preview_model.index(0,0)
        dialog.preview_model.setData(index,Qt.CheckState.Unchecked,Qt.ItemDataRole.CheckStateRole)
        dialog.selected_ack.setChecked(True)
        dialog.original_ack.setChecked(True)
        assert dialog.confirm.isEnabled()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(DeleteDialog,'exec',confirm)
    page.suggest.click()
    wait_for(lambda:len(page.checked)==4 and not window.worker.isRunning())
    assert not service.backend.calls
    window.monitor_updated({'result':{'changed':0,'deleted':0,'errors':[]}})
    assert len(page.checked)==4
    first_checked=next(iter(page.checked))
    page.recycle.click()
    wait_for(lambda:bool(results) and not window.worker.isRunning())
    assert results[0]['result']['success']==3 and Path(first_checked).exists()
    assert first_checked not in service.backend.calls
    window.monitor_updated({'result':{'changed':1}})
    assert not page.checked and not page.suggest.isEnabled()
    window.close()
