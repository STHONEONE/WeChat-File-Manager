import time
from app.file_monitor import FileMonitor
from app.core import canonical
from tests.test_core import fixture

def wait_for(predicate,timeout=10):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if predicate():return
        time.sleep(.05)
    raise AssertionError('monitor update timed out')

def test_native_create_modify_delete_and_restart(tmp_path):
    store,root,p=fixture(tmp_path);store.scan();updates=[]
    monitor=FileMonitor(store,updates.append,debounce=.1,max_wait=.3)
    try:
        assert monitor.start();wait_for(lambda:'监控中' in monitor.state)
        f=p/'monitored.txt';f.write_bytes(b'one')
        wait_for(lambda:bool(store.search(query='monitored.txt')))
        path=canonical(f);store.annotate(path,'自动监控备注','演示',True)
        f.write_bytes(b'two-two')
        wait_for(lambda:store.search(query='monitored.txt')[0]['size']==7)
        f.unlink();wait_for(lambda:bool(store.search(query='monitored.txt',missing=True)))
        assert store.search(query='monitored.txt',missing=True)[0]['note']=='自动监控备注'
        assert monitor.stop();assert monitor.start();wait_for(lambda:'监控中' in monitor.state)
        assert updates
    finally:assert monitor.stop()

def test_monitor_failure_can_be_restarted(tmp_path):
    store,root,p=fixture(tmp_path)
    def fail():raise OSError('simulated watch failure')
    monitor=FileMonitor(store,observer_factory=fail)
    assert not monitor.start() and '异常' in monitor.state
    monitor.observer_factory=None
    try:assert monitor.start();wait_for(lambda:'监控中' in monitor.state)
    finally:monitor.stop()

def test_periodic_reconciliation_recovers_dropped_events(tmp_path):
    store,root,p=fixture(tmp_path);monitor=FileMonitor(store,reconcile_interval=.3,debounce=.05)
    try:
        assert monitor.start();wait_for(lambda:'监控中' in monitor.state)
        monitor.feed=lambda *args:None
        (p/'lost-event.txt').write_bytes(b'demo')
        wait_for(lambda:bool(store.search(query='lost-event.txt')))
        assert store.setting('state:scan')['complete']
    finally:monitor.stop()
