"""Build reviewable duplicate suggestions from the entire indexed result."""
from dataclasses import dataclass
from itertools import groupby

from app.delete_service import DeleteItem
from app.duplicate_detector import VALID_JOIN, HashCancelled
from app.snapshots import indexed_signature


@dataclass
class CleanupSelection:
    eligible: dict
    keepers: dict
    blocked: dict
    stamp: float

    def suggestions(self):
        return {path: row for path, row in self.eligible.items()
                if self.keepers[row['group']] != path}


def build_selection(service, cancelled, progress):
    store = service.store
    state = store.setting('state:duplicates', {})
    if not state.get('complete') or state.get('running'):
        raise ValueError('请先完成重复文件检测，再生成清理建议。')
    result = CleanupSelection({}, {}, {}, state['time'])
    query = (
        'SELECT f.*, h.sha256, (SELECT name FROM accounts WHERE path=f.account) account_name'
        + VALID_JOIN
        + ' ORDER BY h.sha256, f.size, (f.favorite OR trim(f.note)<>\'\') DESC, f.path'
    )
    with store.connect() as db:
        for number, (key, members) in enumerate(groupby(
                db.execute(query), lambda row: (row['sha256'], row['size'])), 1):
            rows = list(members)
            if cancelled():
                raise HashCancelled('已取消生成清理建议。')
            if len(rows) < 2:
                continue
            eligible = []
            for row in rows:
                if cancelled():
                    raise HashCancelled('已取消生成清理建议。')
                path = row['path']
                item = DeleteItem(path, row['account'], row['account_name'], row['size'],
                                  indexed_signature(row), row['sha256'])
                try:
                    service._validate(item,row)
                    service.backend.supports(path)
                except (OSError, ValueError) as error:
                    result.blocked[path] = str(error)
                else:
                    eligible.append(dict(row, group=key))
            if eligible:
                result.keepers[key] = eligible[0]['path']
                result.eligible.update((row['path'], row) for row in eligible)
            if number % 25 == 0:
                progress(f'已检查 {number:,} 个重复组')
    return result
