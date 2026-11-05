"""Filename matching on the local index."""
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

from app.duplicate_detector import HashCancelled
from app.paths import EXTENSIONS, linked
from app.snapshots import indexed_signature, safe_parent, signature


def check_cancelled(cancelled):
    if cancelled():
        raise HashCancelled()


VERSION_SUFFIX = re.compile(
    r'(?:[\s._\-–]*(?:副本|复制件|修改版|修订版|更新版|最终版|完整版|定稿|终稿|新版|原版|'
    r'\(\s*\d+\s*\)|(?:version|ver|v)\s*\d+(?:[._-]\d+)*|[\s._\-–]+copy(?:[\s._-]*\d+)?))+$',
    re.IGNORECASE,
)


def name_keys(name):
    title = unicodedata.normalize('NFKC', Path(name).stem).casefold()
    base = VERSION_SUFFIX.sub('', title)
    stem = ''.join(char for char in title if char.isalnum())
    base = ''.join(char for char in base if char.isalnum())
    # Short names need a recognized version suffix or an identical normalized stem.
    wide = any(ord(char) > 127 for char in stem)
    minimum = max(3 if wide else 5, (len(stem) * 3 + 4) // 5, len(stem) - 12)
    yield from (stem[:length] for length in range(minimum, len(stem) + 1))
    if len(base) >= (2 if wide else 4):
        yield base


def name_groups(store, cancelled, progress):
    """Group indexed files by shared name prefixes without reading their contents."""
    with store.connect() as db:
        rows = [dict(row) for row in db.execute(
            "SELECT f.*, a.name account_name FROM files f JOIN accounts a ON a.path=f.account WHERE f.missing=0")]
    candidates = defaultdict(list)
    for row in rows:
        check_cancelled(cancelled)
        path = Path(row['name'])
        extension = path.suffix.casefold()
        if extension not in EXTENSIONS:
            continue
        for key in set(name_keys(row['name'])):
            candidates[key].append(row)
    results = []
    skipped = 0

    def collect(rows):
        nonlocal skipped
        if len(rows) < 2:
            return
        current = []
        for row in rows:
            check_cancelled(cancelled)
            path = Path(row['path'])
            try:
                if not safe_parent(path, row['account']) or linked(path) or signature(path.stat()) != indexed_signature(row):
                    raise OSError('文件状态已变化')
            except OSError:
                skipped += 1
                continue
            current.append(row)
        if len(current) > 1:
            results.append(current)

    memberships = {key:{row['path'] for row in matching} for key,matching in candidates.items() if len(matching)>1}
    for number,key in enumerate(sorted(memberships, key=lambda key: (len(key), key)),1):
        check_cancelled(cancelled)
        matching = candidates[key]
        paths = memberships[key]
        if any(paths < memberships[other] or
               (paths == memberships[other] and (len(other),other)<(len(key),key))
               for other in name_keys(matching[0]['name']) if other in memberships):
            continue
        collect(sorted(matching,key=lambda row:(row['name'],row['path'])))
        if number % 50 == 0:
            progress(f'名称查找 · 已找到 {len(results):,} 组待核对文件')
    return results, skipped
