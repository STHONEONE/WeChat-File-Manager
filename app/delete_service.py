"""Explicit, single-use deletion plans and per-file audit records.

Only ordinary indexed attachments in verified storage roles are eligible.
No folder deletion, automatic duplicate selection, or permanent deletion exists.
"""
import os
import stat
import time
import uuid
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from app.directory_mapper import deletion_path_allowed
from app.duplicate_detector import hash_stream,HashCancelled
from app.snapshots import signature,indexed_signature
from app.paths import canonical
from app.windows_recycle import WindowsRecycle

@dataclass(frozen=True)
class DeleteItem:
    path:str
    account:str
    account_name:str
    size:int
    snapshot:tuple
    sha256:str=''
    allowed:bool=True
    reason:str=''
    keeper:object=None

@dataclass(frozen=True)
class DeletePlan:
    token:str
    created:float
    items:tuple
    duplicate:bool=False

class DeleteService:
    def __init__(self,store,backend=None,settle_seconds=1.):
        self.store=store;self.backend=backend or WindowsRecycle();self.settle_seconds=settle_seconds;self._plans={}

    def _row(self,path):
        with self.store.connect() as db:
            row=db.execute('SELECT f.*,a.name account_name FROM files f JOIN accounts a ON a.path=f.account WHERE f.path=?',(path,)).fetchone()
            return dict(row) if row else None

    def _validate(self,item,row=None):
        if row is None:
            row=self._row(item.path)
        if not row or row['missing']:raise ValueError('文件已不存在或不在当前索引中。')
        if row['account']!=item.account or not deletion_path_allowed(item.path,row['account']):raise ValueError('不在已确认用途的普通文件管理范围，或属于禁止删除的内部资源。')
        p=Path(item.path)
        # Check every ancestor, including those above the configured account root.
        for component in (p,*p.parents):
            info=os.lstat(component)
            if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:raise ValueError('拒绝目录联接、符号链接或重解析点。')
        s=p.stat()
        if not stat.S_ISREG(s.st_mode):raise ValueError('只允许单个普通文件，不允许目录或特殊设备。')
        if getattr(s,'st_file_attributes',0)&(0x2|0x4|0x4000):raise ValueError('隐藏、系统或加密属性文件不进入删除流程。')
        if not s.st_ino or signature(s)!=item.snapshot or indexed_signature(row)!=item.snapshot:raise ValueError('文件大小、时间或身份已变化，请刷新后重新选择。')
        if time.time()-max(s.st_mtime,s.st_ctime)<self.settle_seconds:raise ValueError('文件最近仍在变化，请等待稳定后重新确认。')

    def prepare(self,paths,duplicate=False,cancelled=lambda:False,progress=lambda text:None,selection=None,expected_snapshots=None):
        from dataclasses import replace
        from app.duplicate_detector import VALID_JOIN
        paths=list(dict.fromkeys(canonical(path) for path in paths))
        selected=set(paths)
        keepers={}
        group_counts={}
        items=[]
        for path in paths:
            if cancelled():raise ValueError('准备已取消，未执行任何删除。')
            row=self._row(path)
            if not row:
                items.append(DeleteItem(path,'','未知',0,(),allowed=False,reason='非索引文件；未登记来源的归档副本也不进入删除流程。'));continue
            expected=''
            if duplicate:
                with self.store.connect() as db:
                    cache=db.execute('SELECT * FROM hash_cache WHERE path=? AND valid=1',(path,)).fetchone()
                if cache and indexed_signature(cache)==indexed_signature(row):expected=cache['sha256']
            item=DeleteItem(path,row['account'],row['account_name'],row['size'],indexed_signature(row),expected)
            try:
                if expected_snapshots is not None and expected_snapshots.get(path)!=item.snapshot:
                    raise ValueError('文件已与查找结果不同，请重新查找后再勾选。')
                self._validate(item)
                if duplicate and not expected:raise ValueError('没有有效重复检测哈希，请重新检测后选择。')
                if duplicate:
                    key=(expected,item.size)
                    if key not in group_counts:
                        with self.store.connect() as db:
                            group_counts[key]=db.execute('SELECT count(*)'+VALID_JOIN+' AND h.sha256=? AND f.size=?',key).fetchone()[0]
                    if group_counts[key]<2:raise ValueError('当前已不是已确认的重复组。')
                    if selection is not None:
                        state=self.store.setting('state:duplicates',{})
                        if not state.get('complete') or state.get('running'):
                            raise ValueError('检测结果已失效，请重新检测。')
                        if selection.stamp != state.get('time'):
                            raise ValueError('检测结果已更新，请重新生成清理清单。')
                        proposal=selection.eligible.get(path)
                        if not proposal or proposal['group']!=key or indexed_signature(proposal)!=item.snapshot:
                            raise ValueError('文件与清理建议不一致，请重新检测。')
                        if key not in keepers:
                            keeper_path=selection.keepers.get(key)
                            if keeper_path not in selection.eligible or keeper_path in selected:
                                raise ValueError('该组必须保留至少一份。')
                            keeper=selection.eligible[keeper_path]
                            keepers[key]=DeleteItem(keeper_path,keeper['account'],keeper['account_name'],
                                                    keeper['size'],indexed_signature(keeper),expected)
                        self._validate(keepers[key])
                        item=replace(item,keeper=keepers[key])
                self.backend.supports(path)
            except Exception as e:item=DeleteItem(item.path,item.account,item.account_name,item.size,item.snapshot,item.sha256,False,str(e))
            items.append(item)
            if len(items)%25==0:progress(f'预检查 {len(items)} 个明确选择的文件；尚未删除')
        plan=DeletePlan(uuid.uuid4().hex,time.time(),tuple(items),duplicate)
        self._plans={plan.token:plan}
        return plan

    def _log(self,plan,item,result,reason,log_id=None):
        with self.store.connect() as db:
            if log_id is not None:
                db.execute('UPDATE deletion_log SET time=?,result=?,reason=? WHERE id=?',(time.time(),result,reason,log_id));return log_id
            cursor=db.execute('INSERT INTO deletion_log(operation_id,time,path,size,account,sha256,result,reason) VALUES (?,?,?,?,?,?,?,?)',
                (plan.token,time.time(),item.path,item.size,item.account,item.sha256,result,reason))
            return cursor.lastrowid

    def execute(self,plan,confirmed=False,original_ack=False,cancelled=lambda:False,progress=lambda text:None,excluded=()):
        if self._plans.pop(plan.token,None) is not plan:raise ValueError('清理计划无效或已使用，请重新选择并确认。')
        if time.time()-plan.created>300:raise ValueError('确认计划已超过 5 分钟，请重新检查文件。')
        results=[]
        for number,item in enumerate(plan.items,1):
            status='skipped';reason='';log_id=None;attempted=False
            if item.path in excluded:status='skipped';reason='用户在预览中取消选择。'
            elif not confirmed or cancelled():status='cancelled';reason='用户取消，未执行该文件。'
            elif not original_ack:reason='未额外确认微信原始附件路径引用风险。'
            elif not item.allowed:reason=item.reason
            else:
                try:
                    # Persist intent first; logging failure prevents the file operation.
                    log_id=self._log(plan,item,'pending','执行中；中断后需核对回收站和原路径。')
                    with self.store._index_lock:
                        self._validate(item);self.backend.supports(item.path)
                        with ExitStack() as pins:
                            if item.keeper:
                                keeper=item.keeper
                                self._validate(keeper)
                                pin_keeper=getattr(self.backend,'pin_keeper',self.backend.pin)
                                pins.enter_context(pin_keeper(keeper.path,keeper.account))
                                self._validate(keeper)
                                if hash_stream(keeper.path,cancelled)!=item.sha256:
                                    raise ValueError('保留文件内容已变化，已跳过。')
                            pins.enter_context(self.backend.pin(item.path,item.account))
                            self._validate(item)
                            if item.sha256:
                                if hash_stream(item.path,cancelled)!=item.sha256:raise ValueError('内容哈希与确认的重复组不一致，已跳过。')
                                self._validate(item)
                            if cancelled():raise HashCancelled()
                            attempted=True
                            def guard():
                                self._validate(item)
                                if item.keeper:self._validate(item.keeper)
                            self.backend.recycle(item.path,guard)
                        if os.path.lexists(item.path):raise OSError('Shell 返回后原路径仍存在，不能确认回收成功。')
                        sync=self.store.update_paths([item.path])
                        status='success';reason='已确认移入系统回收站；不代表磁盘空间已释放。'
                        if sync['errors']:reason+=' 索引同步有异常，请手动扫描。'
                except HashCancelled:status='cancelled';reason='用户取消，未执行该文件。'
                except ValueError as e:status='skipped';reason=str(e)
                except FileNotFoundError:
                    if attempted and not os.path.lexists(item.path):
                        status='uncertain';reason='Shell 调用后原路径不存在，但未收到回收成功确认；请核对回收站。';self.store.update_paths([item.path])
                    else:status='skipped';reason='执行前文件已不存在，未调用永久删除。'
                except Exception as e:
                    status='failed' if os.path.lexists(item.path) else 'uncertain'
                    reason=str(e)
                    if status=='uncertain':
                        reason+=' 原路径已不存在但 Shell 未确认，请核对回收站；不宣称可自动恢复。'
                        self.store.update_paths([item.path])
            self._log(plan,item,status,reason,log_id)
            results.append({'path':item.path,'size':item.size,'result':status,'reason':reason})
            if number%20==0 or number==len(plan.items):
                progress(f'回收站处理 {number}/{len(plan.items)}')
        return {'items':results,'success':sum(r['result']=='success' for r in results),'failed':sum(r['result']=='failed' for r in results),
                'skipped':sum(r['result']=='skipped' for r in results),'cancelled':sum(r['result']=='cancelled' for r in results),
                'uncertain':sum(r['result']=='uncertain' for r in results),'recycled_bytes':sum(r['size'] for r in results if r['result']=='success')}

    def history(self,limit=200,offset=0):
        if not 1<=limit<=1000 or offset<0:raise ValueError('分页范围无效')
        with self.store.connect() as db:return [dict(r) for r in db.execute('SELECT * FROM deletion_log ORDER BY time DESC,id DESC LIMIT ? OFFSET ?',(limit,offset))]
