"""Read-only source scanner and local metadata store. No source mutations."""
import csv
import hashlib
import os
import re
import shutil
import sqlite3
import stat
import time
from datetime import datetime
from pathlib import Path

from app.paths import *

from app.database import Database

from app.search import SearchMixin
from app.scanner import ScannerMixin

from app.annotations import AnnotationMixin
from app.duplicate_detector import DuplicateMixin

class Store(DuplicateMixin, AnnotationMixin, SearchMixin, ScannerMixin, Database):
    def setting(self,key,default=None):
        import json
        with self.connect() as db:row=db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
        if row is None:return default
        try:return json.loads(row[0])
        except (ValueError,TypeError):return default

    def set_setting(self,key,value):
        import json
        with self.connect() as db:db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',(key,json.dumps(value,ensure_ascii=False)))
    def accounts(self):
        with self.connect() as db: return [dict(r) for r in db.execute('SELECT * FROM accounts ORDER BY name')]

    def add(self, root):
        found = discover(root)
        if not found: raise ValueError('未识别到微信账号目录，请选择包含 msg 或 FileStorage 的目录，或其上一级目录。')
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('source:'+canonical(root),canonical(root)))
            for p in found:
                db.execute('INSERT OR IGNORE INTO accounts(path,name) VALUES (?,?)', (canonical(p),p.name))
        return len(found)

    def source_roots(self):
        with self.connect() as db:
            return [r[0] for r in db.execute("SELECT value FROM settings WHERE key LIKE 'source:%'")]+[a['path'] for a in self.accounts()]

    def rename(self, path, name, note=None):
        with self.connect() as db:
            if note is not None: db.execute('UPDATE accounts SET name=?,note=? WHERE path=?',(name,note,path))
            else: db.execute('UPDATE directories SET alias=? WHERE path=?',(name,path))

    def directories(self, account=None):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM directories'+(' WHERE account=?' if account else '')+' ORDER BY path', (account,) if account else ())]

    def alias(self, path, value):
        self.rename(path,value)
        with self.connect() as db: db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('alias:'+path,value))


from app.file_service import digest, export_files
