"""Native watchdog events, bounded coalescing and periodic reconciliation."""
import threading
import time
from pathlib import Path
from app.paths import canonical,linked
from app.snapshots import account_for,internal,managed

class FileMonitor:
    def __init__(self,store,on_update=lambda value:None,on_status=lambda value:None,debounce=.6,max_wait=2.,reconcile_interval=900.,observer_factory=None):
        self.store=store;self.on_update=on_update;self.on_status=on_status
        self.debounce=debounce;self.max_wait=max_wait;self.reconcile_interval=reconcile_interval;self.observer_factory=observer_factory
        self._mutex=threading.Lock();self._stop=threading.Event();self._pending=set();self._rescan=False
        self._first=0.;self._last=0.;self.observer=None;self.thread=None;self.state='空闲'

    def status(self,text):
        self.state=text
        self.store.set_setting('state:monitor',{'text':text,'time':time.time(),'error':'异常' in text})
        self.on_status(text)

    def start(self):
        if self.thread and self.thread.is_alive():return True
        accounts=self.store.accounts()
        roots=sorted({a['path'] for a in accounts},key=len)
        self.roots=[]
        for root in roots:
            if not any(Path(root).is_relative_to(Path(parent)) for parent in self.roots):self.roots.append(root)
        if not self.roots:self.status('监控未启动：请先添加账号目录');return False
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
            service=self
            class Handler(FileSystemEventHandler):
                def on_any_event(self,event):
                    if event.event_type not in {'created','modified','deleted','moved'}:return
                    service.feed([event.src_path,getattr(event,'dest_path','')],event.is_directory)
            self.observer=(self.observer_factory or Observer)()
            for root in self.roots:
                if linked(root) or not Path(root).is_dir():raise OSError('监控根目录不可访问：'+root)
                self.observer.schedule(Handler(),root,recursive=True)
            self.observer.start()
        except Exception as e:
            if self.observer:
                self.observer.stop()
                if self.observer.is_alive():self.observer.join(timeout=2)
            self.status('监控异常：'+str(e)+'；可重启监控或手动扫描');return False
        self._stop.clear()
        with self._mutex:self._rescan=True;self._first=self._last=time.monotonic()
        self.thread=threading.Thread(target=self._run,name='WFM-index-monitor',daemon=True);self.thread.start()
        return True

    def feed(self,paths,directory=False):
        now=time.monotonic();accounts=[{'path':r} for r in getattr(self,'roots',[])]
        with self._mutex:
            touched=False
            for raw in paths:
                if not raw:continue
                path=canonical(raw);root=account_for(path,accounts)
                if root is None or internal(path if directory else Path(path).parent,root):continue
                if directory:self._rescan=True;touched=True
                elif managed(path,root):self._pending.add(path);touched=True
            if len(self._pending)>2000:self._pending.clear();self._rescan=True
            if touched:
                if not self._first:self._first=now
                self._last=now

    def _run(self):
        last_full=0.;last_health=0.
        while not self._stop.wait(.05):
            now=time.monotonic()
            if now-last_health>=2:
                last_health=now
                unhealthy=not self.observer.is_alive() or any(not p.is_alive() for p in self.observer.emitters) or any(not Path(r).is_dir() for r in self.roots)
                if unhealthy:
                    self.status('监控异常：目录或原生事件线程不可用，请重启监控；索引状态保留')
                    continue
            if now-last_full>=self.reconcile_interval:
                with self._mutex:self._rescan=True
            with self._mutex:
                ready=self._rescan or self._pending and (now-self._last>=self.debounce or now-self._first>=self.max_wait)
                if not ready:continue
                full=self._rescan;paths=list(self._pending);self._pending.clear();self._rescan=False;self._first=0.
            try:
                self.status('监控校正扫描中' if full else f'监控更新中：{len(paths)} 个文件事件')
                result=self.store.scan(cancelled=self._stop.is_set) if full else self.store.update_paths(paths,cancelled=self._stop.is_set)
                if full:last_full=time.monotonic()
                self.on_update({'kind':'scan' if full else 'events','result':result})
                if result.get('errors'):self.status(f'监控异常：{len(result["errors"])} 个访问问题，旧备注保留；可手动扫描或重启')
                elif not result.get('cancelled'):self.status('监控中 · 原生事件已启用')
            except Exception as e:self.status('监控更新异常：'+str(e)+'；可重启监控或手动扫描')

    def stop(self):
        self._stop.set()
        if self.observer:
            self.observer.stop()
            if self.observer.is_alive():self.observer.join(timeout=3)
        if self.thread and self.thread.is_alive():self.thread.join(timeout=5)
        alive=bool(self.thread and self.thread.is_alive())
        self.status('监控正在停止，等待索引操作完成' if alive else '空闲 · 自动监控已关闭')
        return not alive
