from app.directory_mapper import describe_directory,deletion_path_allowed
from tests.test_core import fixture
from app.core import canonical

def test_anchored_mapping_and_unknown_alias(tmp_path):
    root=tmp_path/'account'
    assert describe_directory(root/'msg'/'file',root)['kind']=='files'
    assert describe_directory(root/'msg'/'unverified',root)['known'] is False
    assert describe_directory(root/'random'/'file',root,'自定义名称')['known'] is False
    assert not deletion_path_allowed(root/'db_storage'/'test.pdf',root)
    assert not deletion_path_allowed(root/'msg'/'attach'/'foo.jpg',root)
    assert deletion_path_allowed(root/'FileStorage'/'Image'/'foo.jpg',root)

def test_directory_note_survives_scan_and_backup_restore(tmp_path):
    store,root,p=fixture(tmp_path);store.scan();account=store.accounts()[0]['path'];path=canonical(p)
    store.set_directory_meta(path,'我的文档','目录备注')
    store.scan();info=store.directory_details(path,account)
    assert info['name']=='我的文档' and info['note']=='目录备注' and info['count']==1 and info['complete']
    backup=tmp_path/'backup.sqlite';store.backup(backup);store.set_directory_meta(path,'changed','changed');store.restore(backup)
    assert store.directory_details(path,account)['note']=='目录备注'

def test_last_success_is_retained_after_failed_scan(tmp_path):
    store,root,p=fixture(tmp_path);store.scan();account=store.accounts()[0]['path'];before=store.directory_details(canonical(p),account)['scanned_at']
    account_path=__import__('pathlib').Path(account);account_path.rename(account_path.parent/'offline');assert store.scan()['errors']
    details=store.directory_details(canonical(p),account)
    assert details['scanned_at']==before and not details['complete']

def test_v12_upgrade_preserves_personal_data_and_makes_backup(tmp_path):
    import sqlite3
    from app.core import Store
    store,root,p=fixture(tmp_path);store.scan();file=store.search()[0]['path'];store.annotate(file,'V1.2 备注','旧标签',True)
    store.alias(canonical(p),'旧目录名称');store.set_setting('monitor:enabled',True)
    with store.connect() as db:
        db.execute('DROP TABLE deletion_log');db.execute('ALTER TABLE directories DROP COLUMN note');db.execute('ALTER TABLE account_scan_state DROP COLUMN last_success');db.execute('PRAGMA user_version=4')
    upgraded=Store(store.path)
    assert upgraded.search()[0]['note']=='V1.2 备注' and upgraded.search(favorite=True)[0]['tags']=='旧标签'
    assert upgraded.directory_info(p)['alias']=='旧目录名称' and upgraded.setting('monitor:enabled') is True
    backups=list((store.path.parent/'backups').glob('before-upgrade-*.sqlite'));assert len(backups)==1
    with sqlite3.connect(backups[0]) as db:assert db.execute('PRAGMA user_version').fetchone()[0]==4
