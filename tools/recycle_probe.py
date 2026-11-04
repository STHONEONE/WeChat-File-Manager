"""Opt-in Windows integration probe, restricted to a newly-created .tmp fixture."""
import argparse
import json
import time
import uuid
from pathlib import Path
from app.core import Store
from app.delete_service import DeleteService

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-native',action='store_true');args=parser.parse_args()
    if not args.run_native:raise SystemExit('Explicit --run-native is required. Only new synthetic files are used.')
    workspace=Path.cwd().resolve();folder=(workspace/'.tmp'/('native-recycle-'+uuid.uuid4().hex)).resolve()
    if not folder.is_relative_to(workspace/'.tmp'):raise SystemExit('Fixture must remain inside this workspace .tmp.')
    source=folder/'xwechat_files'/'wxid_demo'/'msg'/'file';source.mkdir(parents=True)
    selected=source/'synthetic-recycle-test.txt';unselected=source/'unselected-control.txt'
    selected.write_text('Synthetic recycle fixture only.',encoding='utf-8');unselected.write_text('Must remain untouched.',encoding='utf-8')
    store=Store(folder/'metadata'/'index.sqlite');store.add(source.parents[2]);store.scan();time.sleep(1.1)
    service=DeleteService(store);plan=service.prepare([selected])
    if not plan.items[0].allowed:raise RuntimeError(plan.items[0].reason)
    result=service.execute(plan,confirmed=True,original_ack=True)
    assert result['success']==1,result
    assert not selected.exists() and unselected.read_text(encoding='utf-8')=='Must remain untouched.'
    assert store.search(query='synthetic-recycle-test',missing=True)
    report={'synthetic_only':True,'native_recycle_confirmed':True,'unselected_untouched':True,'index_synchronized':True,'audit_recorded':service.history()[0]['result']=='success'}
    (folder/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))

if __name__=='__main__':main()
