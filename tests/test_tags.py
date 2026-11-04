from tests.test_core import fixture

def test_tag_lifecycle_and_restore(tmp_path):
    store,root,p=fixture(tmp_path);(p/'other.pdf').write_bytes(b'demo');store.scan()
    paths=[r['path'] for r in store.search()]
    store.create_tag('空标签');assert store.tags()['空标签']==0
    store.add_tags(paths,'科研, 科研项目');assert store.tags()['科研']==2
    store.rename_tag('科研','论文');assert '科研' not in store.tags()
    assert store.search_page(tag='论文',exact_tag=True).total==2
    assert store.search_page(tag='科研',exact_tag=True).total==0
    backup=tmp_path/'backup.sqlite';store.backup(backup)
    store.delete_tag('论文');assert all('论文' not in r['tags'] for r in store.search())
    assert store.tags()['科研项目']==2
    store.restore(backup);assert store.tags()['论文']==2 and '空标签' in store.tags()
    store.rename_tag('论文','科研项目');assert store.tags()['科研项目']==2

def test_tag_name_validation(tmp_path):
    import pytest
    store,root,p=fixture(tmp_path)
    for name in ('', ' ', 'a,b','a，b','a\nb'):
        with pytest.raises(ValueError):store.create_tag(name)
