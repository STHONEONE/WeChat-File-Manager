import time
from app.core import Store,canonical
from app.ui.file_model import FilesModel

def populate(store,n=50000):
    root=canonical('D:/WFM-Demo/wxid_demo')
    with store.connect() as db:
        db.execute('INSERT INTO accounts(path,name) VALUES (?,?)',(root,'虚构演示账号'))
        db.executemany('INSERT INTO files(path,account,name,category,size,mtime,month,identity,seen,note,tags,favorite) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            [(root+f'/msg/file/示例-{i:06}.pdf',root,f'示例-{i:06}.pdf','文档',i,1700000000+i,'2026-10',str(i),'demo','中文备注' if i%10==0 else '', '科研, 论文' if i%10==0 else '', int(i%10==0)) for i in range(n)])
    return root

def test_50000_pagination_and_metadata_search(tmp_path):
    store=Store(tmp_path/'index.sqlite');root=populate(store)
    t=time.perf_counter();page=store.search_page();elapsed=time.perf_counter()-t
    assert page.total==50000 and len(page.rows)==200
    assert elapsed<5  # A broad regression ceiling, not a claimed latency promise.
    other=store.search_page(offset=200)
    assert not {r['path'] for r in page.rows}&{r['path'] for r in other.rows}
    assert store.search_page(query='中文备注',favorite=True,tag='科研',account=root,category='文档').total==5000
    assert store.search_page(query='示例-000001.pdf').total==1
    ordered=store.search_page(order='size',descending=False,offset=200)
    assert ordered.rows[0]['size']==200
    model=FilesModel();model.configure(store,{},'mtime',True,page)
    assert model.rowCount()==200 and model.canFetchMore()
    model.fetchMore();assert model.rowCount()==400

def test_lazy_directory_children(tmp_path):
    store=Store(tmp_path/'index.sqlite');root=canonical(tmp_path/'account')
    with store.connect() as db:
        db.executemany('INSERT INTO directories(path,account,parent) VALUES (?,?,?)',[(str(tmp_path/'account'/str(i)),root,root) for i in range(1000)])
    assert len(store.directory_children(root))==200
    assert len(store.directory_children(root,offset=900))==100
