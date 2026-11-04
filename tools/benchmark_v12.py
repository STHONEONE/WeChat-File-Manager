"""Synthetic V1.1/V1.2 comparison. Baseline checkout must be supplied explicitly."""
import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path
from app.core import Store
from app.file_monitor import FileMonitor
from tools.benchmark import hardware

PROGRAM=r'''
import json,sys,time,statistics
from pathlib import Path
from app.core import Store
from tests.test_search import populate
class TrackedStore(Store):
    trace=False
    file_writes=0
    def connect(self):
        db=super().connect()
        if self.trace:
            def count(sql):
                s=sql.strip().upper()
                if s.startswith('INSERT INTO FILES') or s.startswith('UPDATE FILES') or s.startswith('DELETE FROM FILES'):self.file_writes+=1
            db.set_trace_callback(count)
        return db
root,dbpath=sys.argv[1:3];store=TrackedStore(dbpath);store.add(root)
t=time.perf_counter();store.scan();first=time.perf_counter()-t
t=time.perf_counter();second=store.scan();repeat=time.perf_counter()-t
store.trace=True;store.scan()
queries=Store(str(Path(dbpath).with_name('queries.sqlite')));populate(queries)
results={}
for name,filters in {'first':{},'chinese':{'query':'中文备注'},'last':{'offset':49800}}.items():
    times=[]
    for i in range(7):
        t=time.perf_counter();page=queries.search_page(**filters);times.append((time.perf_counter()-t)*1000)
    assert len(page.rows)==200
    results[name]={'median_ms':round(statistics.median(times),3),'max_ms':round(max(times),3)}
print(json.dumps({'first_scan_seconds':round(first,4),'unchanged_scan_seconds':round(repeat,4),'unchanged_file_write_statements':store.file_writes,'query_50000':results}))
'''

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--baseline',type=Path,required=True);args=parser.parse_args()
    here=Path.cwd();folder=here/'.tmp'/f'benchmark-v12-{time.time_ns()}'
    root=folder/'scan'/'wxid_demo';source=root/'msg'/'file';source.mkdir(parents=True)
    for i in range(2000):(source/f'synthetic-{i:05}.txt').write_text('demo',encoding='utf-8')
    versions={}
    for name,cwd in [('v1.1',args.baseline.resolve()),('v1.2',here)]:
        db=folder/name/'scan.sqlite'
        p=subprocess.run([sys.executable,'-c',PROGRAM,str(root),str(db)],cwd=cwd,check=True,capture_output=True,text=True)
        versions[name]=json.loads(p.stdout)
    droot=folder/'duplicates'/'wxid_demo'/'msg'/'file';droot.mkdir(parents=True)
    for i in range(20):
        for j in range(2):(droot/f'demo-{i}-{j}.bin').write_bytes(bytes([i])*8192)
    for i in range(2):(droot/f'empty-{i}.txt').touch();(droot/f'large-{i}.bin').write_bytes(b'x'*(4*1024*1024))
    store=Store(folder/'hash-data'/'index.sqlite');store.add(droot.parents[2]);store.scan()
    first=store.detect_duplicates(settle_seconds=0);repeat=store.detect_duplicates(settle_seconds=0)
    delays=[];monitor=FileMonitor(store,debounce=.2,max_wait=.5)
    try:
        assert monitor.start()
        deadline=time.monotonic()+10
        while '监控中' not in monitor.state and time.monotonic()<deadline:time.sleep(.02)
        assert '监控中' in monitor.state
        for i in range(3):
            start=time.perf_counter();name=f'monitor-demo-{i}.txt';(droot/name).write_bytes(b'monitor demo')
            while not store.search(query=name):
                if time.perf_counter()-start>10:raise TimeoutError('native monitor timed out')
                time.sleep(.02)
            delays.append(round((time.perf_counter()-start)*1000,3))
    finally:assert monitor.stop()
    report={'hardware':hardware(),'scan_dataset':'2000 synthetic 4-byte files, same physical directory for both versions',
            'baseline_commit':'26756e7ff1bc6693248dd7c0cf7cdd5d66d7f0d9','versions':versions,
            'duplicates':{'dataset':'44 synthetic files: 20 identical pairs, 2 empty files, 2 x 4 MiB files',
                'first_seconds':first['seconds'],'repeat_seconds':repeat['seconds'],'first_hashed':first['hashed'],'repeat_hashed':repeat['hashed'],'cache_hit_rate':repeat['cache_hit_rate']},
            'monitor':{'debounce_seconds':.2,'native_update_ms':delays},
            'notes':['No source contents or private paths in this report.','File write counts measured in a separate traced scan; timings measured without tracing.','Full traversal is still required; OS disk cache can affect comparison.']}
    Path('docs/V1.2性能测试.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
