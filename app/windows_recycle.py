"""Windows-only, recycle-required Shell adapter. There is no legacy fallback."""
import os
import re
from contextlib import contextmanager
from pathlib import Path

class WindowsRecycle:
    def supports(self,path):
        if os.name!='nt':raise OSError('仅支持 Windows 系统回收站，不提供永久删除回退。')
        import ctypes
        from ctypes import wintypes
        p=Path(path)
        if not re.fullmatch('[A-Za-z]:',p.drive) or str(p).startswith('\\\\'):raise OSError('拒绝网络路径、设备路径或非本地盘路径。')
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        volume=ctypes.create_unicode_buffer(1024)
        kernel.GetVolumePathNameW.argtypes=[wintypes.LPCWSTR,wintypes.LPWSTR,wintypes.DWORD]
        if not kernel.GetVolumePathNameW(str(p),volume,len(volume)):raise ctypes.WinError(ctypes.get_last_error())
        kernel.GetDriveTypeW.argtypes=[wintypes.LPCWSTR]
        if kernel.GetDriveTypeW(volume.value)!=3:raise OSError('只允许本地固定磁盘；网络盘和可移动设备不进入删除流程。')
        fs=ctypes.create_unicode_buffer(128)
        kernel.GetVolumeInformationW.argtypes=[wintypes.LPCWSTR,wintypes.LPWSTR,wintypes.DWORD,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.LPWSTR,wintypes.DWORD]
        if not kernel.GetVolumeInformationW(volume.value,None,0,None,None,None,fs,len(fs)):raise ctypes.WinError(ctypes.get_last_error())
        if fs.value.upper()!='NTFS':raise OSError('当前仅确认本地 NTFS 回收站行为，其他文件系统拒绝删除。')
        class BinInfo(ctypes.Structure):_fields_=[('cbSize',wintypes.DWORD),('size',ctypes.c_longlong),('items',ctypes.c_longlong)]
        info=BinInfo();info.cbSize=ctypes.sizeof(info)
        query=ctypes.WinDLL('shell32').SHQueryRecycleBinW;query.argtypes=[wintypes.LPCWSTR,ctypes.POINTER(BinInfo)];query.restype=ctypes.c_long
        result=query(volume.value,ctypes.byref(info))
        if result<0:raise OSError(f'无法确认该磁盘回收站可用（HRESULT {result:#x}），已拒绝删除。')

    @contextmanager
    def pin(self,path,root):
        """Deny content writers; pin ancestors against rename/reparse replacement."""
        import win32file,win32con
        handles=[]
        try:
            p=Path(path);root=Path(root)
            for parent in reversed(p.parents):
                handle=win32file.CreateFile(str(parent),0x0080,win32con.FILE_SHARE_READ|win32con.FILE_SHARE_WRITE,None,win32con.OPEN_EXISTING,win32con.FILE_FLAG_BACKUP_SEMANTICS|win32file.FILE_FLAG_OPEN_REPARSE_POINT,None)
                handles.append(handle)
            handle=win32file.CreateFile(str(p),win32con.GENERIC_READ,win32con.FILE_SHARE_READ|win32con.FILE_SHARE_DELETE,None,win32con.OPEN_EXISTING,win32file.FILE_FLAG_OPEN_REPARSE_POINT,None)
            handles.append(handle)
            yield
        finally:
            for handle in reversed(handles):handle.Close()

    def recycle(self,path,guard):
        import pythoncom
        from win32com.shell import shell,shellcon
        from win32com.server.policy import DesignatedWrapPolicy
        from win32com.server.exception import COMException
        pythoncom.CoInitialize()
        class Sink(DesignatedWrapPolicy):
            _com_interfaces_=[shell.IID_IFileOperationProgressSink]
            _public_methods_=['StartOperations','FinishOperations','PreRenameItem','PostRenameItem','PreMoveItem','PostMoveItem','PreCopyItem','PostCopyItem','PreDeleteItem','PostDeleteItem','PreNewItem','PostNewItem','UpdateProgress','ResetTimer','PauseTimer','ResumeTimer']
            success=False
            prechecked=False
            post_result=None
            def __init__(self):self._wrap_(self)
            def PreDeleteItem(self,flags,item):
                if not flags&shellcon.TSF_DELETE_RECYCLE_IF_POSSIBLE:raise COMException(desc='拒绝非回收站删除',scode=-2147467260)
                actual=item.GetDisplayName(shellcon.SIGDN_FILESYSPATH)
                if os.path.normcase(os.path.abspath(actual))!=os.path.normcase(os.path.abspath(path)):raise COMException(desc='Shell 目标与确认路径不一致',scode=-2147467260)
                try:guard()
                except Exception as e:raise COMException(desc=str(e),scode=-2147467260)
                self.prechecked=True
            def PostDeleteItem(self,flags,item,result,new_item):
                self.post_result=result
                self.success=self.prechecked and result>=0 and new_item is not None
            def __getattr__(self,name):
                if name in self._public_methods_:return lambda *args:None
                raise AttributeError(name)
        operation=item=wrapped=None
        try:
            sink=Sink();wrapped=pythoncom.WrapObject(sink,shell.IID_IFileOperationProgressSink)
            operation=pythoncom.CoCreateInstance(shell.CLSID_FileOperation,None,pythoncom.CLSCTX_INPROC_SERVER,shell.IID_IFileOperation)
            # Recycle-required + veto in PreDeleteItem; never invoke SHFileOperation.
            flags=(shellcon.FOF_SILENT|shellcon.FOF_NOERRORUI|shellcon.FOF_NOCONFIRMATION|
                   shellcon.FOF_NO_CONNECTED_ELEMENTS|shellcon.FOF_NORECURSION|0x00080000|0x00100000|0x20000000)
            operation.SetOperationFlags(flags)
            item=shell.SHCreateItemFromParsingName(path,None,shell.IID_IShellItem)
            operation.DeleteItem(item,wrapped)
            result=operation.PerformOperations()
            if result or operation.GetAnyOperationsAborted() or not sink.success:raise OSError(f'Shell 未确认移入回收站（Pre={sink.prechecked}, Post={sink.post_result}），可能取消、受占用或回收站不可用；未执行永久删除回退。')
        finally:
            item=operation=wrapped=None
            pythoncom.CoUninitialize()
