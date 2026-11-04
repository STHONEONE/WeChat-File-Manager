"""Versioned metadata database, bounded connections and WAL-safe restore."""
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA_VERSION = 3
SCHEMA = '''
CREATE TABLE IF NOT EXISTS accounts(path TEXT PRIMARY KEY, name TEXT, note TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS directories(path TEXT PRIMARY KEY, account TEXT, alias TEXT DEFAULT '', count INTEGER DEFAULT 0, size INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, account TEXT, name TEXT, category TEXT, size INTEGER, mtime REAL, month TEXT, identity TEXT, missing INTEGER DEFAULT 0, seen TEXT, note TEXT DEFAULT '', tags TEXT DEFAULT '', favorite INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS file_account ON files(account);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
'''
REQUIRED = {
    'accounts': {'path','name','note'},
    'directories': {'path','account','alias','count','size'},
    'files': {'path','account','name','category','size','mtime','month','identity','missing','seen','note','tags','favorite'},
    'settings': {'key','value'},
}

class Connection(sqlite3.Connection):
    """sqlite's ordinary context manager does not close the connection."""
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()
            if getattr(self, '_owner_lock', None):
                self._owner_lock.release()
                self._owner_lock = None

class Database:
    def __init__(self, path):
        self.path = Path(path).absolute()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self.connect() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version > SCHEMA_VERSION:
                raise ValueError('数据库由更高版本创建，请升级程序。')
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript(SCHEMA)
            self.migrate(db, version)

    @staticmethod
    def migrate(db, version):
        if version < 1:
            # V1.0 had user_version=0. Existing annotation columns stay intact.
            db.execute('PRAGMA user_version=1')
        if version < 2:
            columns={r[1] for r in db.execute('PRAGMA table_info(directories)')}
            if 'parent' not in columns:db.execute('ALTER TABLE directories ADD COLUMN parent TEXT')
            for row in db.execute('SELECT path FROM directories').fetchall():
                db.execute('UPDATE directories SET parent=? WHERE path=?',(str(Path(row[0]).parent),row[0]))
            for sql in (
                'CREATE INDEX IF NOT EXISTS file_recent ON files(missing,mtime DESC,path)',
                'CREATE INDEX IF NOT EXISTS file_category_recent ON files(missing,category,mtime DESC,path)',
                'CREATE INDEX IF NOT EXISTS file_account_recent ON files(missing,account,mtime DESC,path)',
                'CREATE INDEX IF NOT EXISTS file_favorites ON files(missing,favorite,mtime DESC,path)',
                'CREATE INDEX IF NOT EXISTS file_size ON files(missing,size)',
                'CREATE INDEX IF NOT EXISTS directory_parent ON directories(parent,path)',
            ):db.execute(sql)
            db.execute('PRAGMA user_version=2')
        if version < 3:
            db.execute('CREATE TABLE IF NOT EXISTS tag_catalog(name TEXT PRIMARY KEY)')
            for row in db.execute("SELECT DISTINCT tags FROM files WHERE tags<>''").fetchall():
                for tag in row[0].replace('，',',').split(','):
                    if tag.strip():db.execute('INSERT OR IGNORE INTO tag_catalog(name) VALUES (?)',(tag.strip(),))
            db.execute('PRAGMA user_version=3')

    def connect(self):
        self._lock.acquire()
        try:
            db = sqlite3.connect(self.path, timeout=30, factory=Connection)
            db._owner_lock = self._lock
            db.row_factory = sqlite3.Row
            return db
        except Exception:
            self._lock.release()
            raise

    @staticmethod
    def validate(db):
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('备份完整性检查失败。')
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if version > SCHEMA_VERSION:
            raise ValueError('不支持更高版本的备份。')
        for name, columns in REQUIRED.items():
            entry = db.execute('SELECT type FROM sqlite_master WHERE name=?', (name,)).fetchone()
            if not entry or entry[0] != 'table':
                raise ValueError('不是本程序的有效备份：缺少数据表 '+name)
            if not columns <= {r[1] for r in db.execute(f'PRAGMA table_info({name})')}:
                raise ValueError('备份数据表字段不完整：'+name)
        if version>=2 and 'parent' not in {r[1] for r in db.execute('PRAGMA table_info(directories)')}:
            raise ValueError('备份缺少目录索引字段。')
        if version>=3 and not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='tag_catalog'").fetchone():
            raise ValueError('备份缺少标签目录。')
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' LIMIT 1").fetchone():
            raise ValueError('备份包含不支持的触发器。')
        return version

    def backup(self, target):
        target = Path(target).resolve()
        if target == self.path.resolve():
            raise ValueError('备份不能覆盖当前数据库。')
        with self.connect() as src, sqlite3.connect(target, factory=Connection) as dest:
            src.backup(dest)

    def restore(self, source):
        source = Path(source).resolve()
        if source == self.path.resolve():
            raise ValueError('不能从当前正在使用的数据库恢复。')
        if not source.is_file():
            raise ValueError('备份文件不存在。')
        # Snapshot a read-only source, including any committed source WAL frames.
        with self._lock, sqlite3.connect(source.as_uri()+'?mode=ro', uri=True, factory=Connection) as src, sqlite3.connect(':memory:', factory=Connection) as snapshot:
            self.validate(src)
            src.backup(snapshot)
            self.migrate(snapshot, snapshot.execute('PRAGMA user_version').fetchone()[0])
            snapshot.commit()
            self.validate(snapshot)
            folder = self.path.parent/'backups'
            folder.mkdir(exist_ok=True)
            rollback = folder/f'before-restore-{time.time_ns()}.sqlite'
            self.backup(rollback)
            # SQLite's backup API commits atomically and coordinates destination WAL.
            # All app-owned connections are closed after their bounded operations.
            with self.connect() as dest:
                snapshot.backup(dest)
            return rollback
