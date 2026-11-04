from app.statistics import storage_statistics
from tests.test_duplicates import dataset

def test_filtered_bulk_actions_and_statistics(tmp_path):
    store,folder,other=dataset(tmp_path)
    result=store.bulk_manage('add_tags',tags='批量,保留',filters={'query':'empty'})
    assert result['success']==2
    assert store.bulk_manage('favorite',filters={'tag':'批量','exact_tag':True})['success']==2
    assert len(store.search(favorite=True))==2
    store.bulk_manage('remove_tags',tags='批量',filters={'favorite':True})
    assert not store.search(tag='批量') and len(store.search(tag='保留'))==2
    assert store.bulk_manage('unfavorite',paths=[store.search()[0]['path'],'not-indexed'])['failures']
    store.detect_duplicates(settle_seconds=0);stats=storage_statistics(store)
    assert stats['count']==7 and len(stats['accounts'])==2 and stats['duplicates']['groups']==3
    assert sum(c['count'] for c in stats['categories'])==7
    assert stats['largest'][0]['size']==2*1024*1024 and stats['scan']['complete']

def test_bulk_cancel_is_atomic(tmp_path):
    store,folder,other=dataset(tmp_path);calls=0
    def cancelled():
        nonlocal calls
        calls+=1;return calls>2
    result=store.bulk_manage('favorite',cancelled=cancelled)
    assert result['cancelled'] and not store.search(favorite=True)
