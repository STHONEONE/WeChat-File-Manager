import os
from pathlib import Path

import pytest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.cleanup_selection import build_selection
from app.core import Store, canonical
from app.delete_service import DeleteService
from app.duplicate_detector import HashCancelled
from app.ui.delete_dialog import DeleteDialog
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


def test_global_suggestions_span_more_than_one_group_and_member_page(tmp_path):
    store, first, second, service = build_fixture(tmp_path, 201, large_group=202)
    preferred = canonical(second / 'group-000-201.txt')
    store.annotate(preferred, '保留这份', '', True)
    draft = build_selection(service, lambda: False, lambda _: None)
    assert len(draft.keepers) == 201 and len(draft.suggestions()) == 401
    assert sum(row['size'] for row in draft.suggestions().values()) == 1604
    assert preferred in draft.keepers.values() and preferred not in draft.suggestions()


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
