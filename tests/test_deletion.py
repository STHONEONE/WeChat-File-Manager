import os
from contextlib import nullcontext
from pathlib import Path
import pytest
from app.core import canonical
from app.delete_service import DeleteService
from tests.test_core import fixture

class FakeRecycle:
    """Test-only quarantine within the independent fixture. Not a runtime backend."""
    def __init__(self,folder,fail=()):self.folder=folder;folder.mkdir();self.fail=set(fail);self.calls=[]
    def supports(self,path):return None
    def pin(self,path,root):return nullcontext()
    def recycle(self,path,guard):
        guard()
        if Path(path).name in self.fail:raise OSError('simulated recycle unavailable / permission failure')
        self.calls.append(path);Path(path).rename(self.folder/(str(len(self.calls))+'-'+Path(path).name))

def setup(tmp_path):
    store,root,p=fixture(tmp_path);(p/'other.txt').write_bytes(b'demo');store.scan()
    backend=FakeRecycle(tmp_path/'mock-recycle');service=DeleteService(store,backend,settle_seconds=0)
    return store,root,p,backend,service

def test_only_selected_file_recycled_and_annotations_kept(tmp_path):
    store,root,p,backend,service=setup(tmp_path);path=canonical(p/'论文.pdf');store.annotate(path,'保留个人信息','tag',True)
    result=service.execute(service.prepare([path]),confirmed=True,original_ack=True)
    assert result['success']==1 and backend.calls==[path] and (p/'other.txt').exists()
    assert store.search(query='论文.pdf',missing=True)[0]['note']=='保留个人信息'
    assert service.history()[0]['result']=='success'

def test_cancel_and_missing_original_ack_are_non_destructive(tmp_path):
    store,root,p,backend,service=setup(tmp_path)
    assert service.execute(service.prepare([p/'other.txt']))['cancelled']==1
    assert service.execute(service.prepare([p/'other.txt']),confirmed=True)['skipped']==1
    assert not backend.calls and (p/'other.txt').exists()

def test_partial_failure_never_uses_permanent_fallback(tmp_path):
    store,root,p,backend,service=setup(tmp_path);backend.fail.add('other.txt')
    result=service.execute(service.prepare([p/'论文.pdf',p/'other.txt']),True,True)
    assert result['success']==1 and result['failed']==1 and (p/'other.txt').exists()
    assert len(service.history())==2

def test_modified_or_replaced_after_confirmation_is_skipped(tmp_path):
    store,root,p,backend,service=setup(tmp_path);target=p/'other.txt';plan=service.prepare([target])
    target.write_bytes(b'changed content')
    assert service.execute(plan,True,True)['skipped']==1 and target.exists() and not backend.calls
    store.scan();plan=service.prepare([target]);target.rename(p/'old.txt');target.write_bytes(b'changed content')
    assert service.execute(plan,True,True)['skipped']==1

def test_unknown_internal_and_directory_targets_blocked(tmp_path):
    store,root,p,backend,service=setup(tmp_path)
    account=Path(store.accounts()[0]['path']);unknown=account/'unknown';unknown.mkdir();(unknown/'file.txt').write_bytes(b'demo');store.scan()
    protected=account/'db_storage'/'misleading.pdf';protected.write_bytes(b'db data')
    from app.scanner import upsert_file
    with store.connect() as db:upsert_file(db,canonical(protected),canonical(account),protected.name,protected.stat(),None)
    plan=service.prepare([protected,unknown/'file.txt',p,root/'outside.txt'])
    assert all(not item.allowed for item in plan.items)
    result=service.execute(plan,True,True);assert result['skipped']==4 and not backend.calls

def test_reparse_ancestor_blocked(tmp_path,monkeypatch):
    store,root,p,backend,service=setup(tmp_path);original=os.lstat
    def reparse(path,*args,**kwargs):
        result=original(path,*args,**kwargs)
        if canonical(path)==canonical(p):
            from types import SimpleNamespace
            return SimpleNamespace(st_mode=result.st_mode,st_file_attributes=0x400)
        return result
    monkeypatch.setattr(os,'lstat',reparse)
    plan=service.prepare([p/'other.txt']);assert not plan.items[0].allowed
    assert service.execute(plan,True,True)['skipped']==1 and not backend.calls

def test_duplicate_selection_rehashes_and_leaves_unselected_copy(tmp_path,monkeypatch):
    from tests.test_duplicates import dataset
    from app import delete_service
    store,p,other=dataset(tmp_path);store.detect_duplicates(settle_seconds=0)
    backend=FakeRecycle(tmp_path/'mock-recycle');service=DeleteService(store,backend,0)
    calls=[];real=delete_service.hash_stream
    def record(path,cancelled):calls.append(path);return real(path,cancelled)
    monkeypatch.setattr(delete_service,'hash_stream',record)
    target=canonical(p/'a.txt');result=service.execute(service.prepare([target],duplicate=True),True,True)
    assert result['success']==1 and calls==[target] and (other/'different-name.txt').exists()
    assert len(store.duplicate_groups())==2

def test_hash_mismatch_is_skipped_without_recycle(tmp_path,monkeypatch):
    from tests.test_duplicates import dataset
    from app import delete_service
    store,p,other=dataset(tmp_path);store.detect_duplicates(settle_seconds=0)
    backend=FakeRecycle(tmp_path/'mock-recycle');service=DeleteService(store,backend,0)
    monkeypatch.setattr(delete_service,'hash_stream',lambda *args:'0'*64)
    assert service.execute(service.prepare([p/'a.txt'],True),True,True)['skipped']==1
    assert not backend.calls and (p/'a.txt').exists()

def test_single_use_and_mid_batch_cancel(tmp_path):
    store,root,p,backend,service=setup(tmp_path);plan=service.prepare([p/'论文.pdf',p/'other.txt'])
    result=service.execute(plan,True,True,cancelled=lambda:bool(backend.calls))
    assert result['success']==1 and result['cancelled']==1 and (p/'other.txt').exists()
    with pytest.raises(ValueError):service.execute(plan,True,True)

def test_recycle_unavailable_blocks_before_execution(tmp_path):
    store,root,p,backend,service=setup(tmp_path)
    def unavailable(path):raise OSError('no recycle bin support')
    backend.supports=unavailable
    plan=service.prepare([p/'other.txt'])
    assert not plan.items[0].allowed
    assert service.execute(plan,True,True)['skipped']==1 and (p/'other.txt').exists() and not backend.calls

def test_logging_failure_prevents_file_operation(tmp_path,monkeypatch):
    store,root,p,backend,service=setup(tmp_path);plan=service.prepare([p/'other.txt'])
    monkeypatch.setattr(service,'_log',lambda *args,**kwargs:(_ for _ in ()).throw(OSError('simulated database write failure')))
    with pytest.raises(OSError):service.execute(plan,True,True)
    assert (p/'other.txt').exists() and not backend.calls

def test_delete_history_is_in_metadata_backup(tmp_path):
    store,root,p,backend,service=setup(tmp_path)
    service.execute(service.prepare([p/'other.txt']),True,True)
    saved=service.history();backup=tmp_path/'with-audit.sqlite';store.backup(backup)
    with store.connect() as db:db.execute('DELETE FROM deletion_log')
    store.restore(backup);assert service.history()==saved

def test_missing_success_receipt_is_reported_as_uncertain(tmp_path):
    store,root,p,backend,service=setup(tmp_path);original=backend.recycle
    def incomplete(path,guard):original(path,guard);raise FileNotFoundError('simulated missing Shell receipt')
    backend.recycle=incomplete
    result=service.execute(service.prepare([p/'other.txt']),True,True)
    assert result['uncertain']==1 and result['success']==0 and (p/'论文.pdf').exists()
    assert store.search(query='other.txt',missing=True) and service.history()[0]['result']=='uncertain'

@pytest.mark.skipif(os.name!='nt',reason='Windows sharing semantics')
def test_open_writer_is_rejected_before_recycle(tmp_path):
    import win32file,win32con
    from app.windows_recycle import WindowsRecycle
    store,root,p,backend,service=setup(tmp_path)
    backend.pin=lambda path,root:WindowsRecycle().pin(path,root)
    plan=service.prepare([p/'other.txt'])
    handle=win32file.CreateFile(str(p/'other.txt'),win32con.GENERIC_WRITE,win32con.FILE_SHARE_READ|win32con.FILE_SHARE_WRITE|win32con.FILE_SHARE_DELETE,None,win32con.OPEN_EXISTING,0,None)
    try:
        result=service.execute(plan,True,True)
        assert result['failed']==1 and not backend.calls and (p/'other.txt').exists()
        assert '32' in result['items'][0]['reason'] or 'sharing' in result['items'][0]['reason'].lower() or '共享' in result['items'][0]['reason']
    finally:handle.Close()
