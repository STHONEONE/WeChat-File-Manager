import os
import pytest

@pytest.mark.skipif(os.name!='nt',reason='Windows COM adapter')
@pytest.mark.parametrize('mode',['success','non_recycle','no_receipt','cancel'])
def test_shell_must_confirm_recycling_and_veto_permanent_modes(tmp_path,monkeypatch,mode):
    import pythoncom
    from win32com.shell import shell
    from app.windows_recycle import WindowsRecycle
    path=tmp_path/'synthetic.txt';path.write_bytes(b'fixture');guards=[]
    class Item:
        def GetDisplayName(self,flags):return str(path)
    class Operation:
        def SetOperationFlags(self,flags):assert flags&0x00080000 and flags&0x00100000 and flags&0x2000
        def DeleteItem(self,item,sink):self.item=item;self.sink=sink
        def PerformOperations(self):
            self.sink.PreDeleteItem(0 if mode=='non_recycle' else 0x80,self.item)
            self.sink.PostDeleteItem(0x80,self.item,0x270000,object() if mode!='no_receipt' else None)
            return 0
        def GetAnyOperationsAborted(self):return mode=='cancel'
    monkeypatch.setattr(pythoncom,'CoCreateInstance',lambda *args:Operation())
    monkeypatch.setattr(pythoncom,'WrapObject',lambda policy,*args:policy)
    monkeypatch.setattr(shell,'SHCreateItemFromParsingName',lambda *args:Item())
    if mode=='success':WindowsRecycle().recycle(str(path),lambda:guards.append(True));assert guards==[True]
    else:
        with pytest.raises(Exception):WindowsRecycle().recycle(str(path),lambda:guards.append(True))
        if mode=='non_recycle':assert not guards
    assert path.read_bytes()==b'fixture'  # Mocked Shell never mutates test files.

@pytest.mark.skipif(os.name!='nt',reason='Windows volume policy')
def test_network_and_device_paths_are_rejected():
    from app.windows_recycle import WindowsRecycle
    for path in [r'\\server\share\file.txt',r'\\?\C:\file.txt',r'\\.\PhysicalDrive0']:
        with pytest.raises(OSError):WindowsRecycle().supports(path)
