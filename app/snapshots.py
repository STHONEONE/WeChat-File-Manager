"""Source metadata and access policy, shared by scan/monitor/hash operations."""
import os
from pathlib import Path
from app.paths import canonical,linked,SYSTEM,INTERNAL

def identity(s):
    return f'{s.st_dev}:{s.st_ino}:{getattr(s,"st_birthtime_ns",0)}'

def signature(s):
    return (s.st_size,s.st_mtime_ns,s.st_ctime_ns,identity(s))

def indexed_signature(row):
    return (row['size'],row['mtime_ns'],row['ctime_ns'],row['identity'])

def internal(path,root):
    try:return any(p.lower() in SYSTEM for p in Path(path).relative_to(root).parts)
    except ValueError:return True

def managed(path,root):
    p=Path(path);ext=p.suffix.lower()
    return bool(ext and not internal(p.parent,root) and ext not in INTERNAL and not ext.startswith('.kvdb'))

def safe_parent(path,root):
    p=Path(canonical(path));root=Path(canonical(root))
    if not p.is_relative_to(root):return False
    parent=p.parent
    while parent.is_relative_to(root):
        if linked(parent):return False
        if parent==root:return True
        parent=parent.parent
    return False

def account_for(path,accounts):
    p=Path(canonical(path))
    return next((a['path'] for a in accounts if p.is_relative_to(Path(a['path']))),None)
