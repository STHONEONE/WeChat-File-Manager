"""Image decoding runs off the UI thread and stale results are discarded."""
from PySide6.QtCore import QObject,QRunnable,QThreadPool,Signal,Slot,QSize,Qt
from PySide6.QtGui import QImageReader

class PreviewSignals(QObject):
    done=Signal(int,object,str)

class Decode(QRunnable):
    def __init__(self,token,path,size,signals):
        super().__init__();self.token=token;self.path=path;self.size=size;self.signals=signals
    def run(self):
        try:
            reader=QImageReader(self.path);size=reader.size()
            if self.size>40*1024**2 or size.width()*size.height()>60_000_000:
                self.signals.done.emit(self.token,None,'图片过大，请使用系统程序打开');return
            size.scale(QSize(640,480),Qt.AspectRatioMode.KeepAspectRatio);reader.setScaledSize(size);reader.setAutoTransform(True)
            img=reader.read();self.signals.done.emit(self.token,img,'' if not img.isNull() else '无法预览此图片，请使用系统程序打开')
        except Exception as e:self.signals.done.emit(self.token,None,'预览失败：'+str(e))

class PreviewController(QObject):
    ready=Signal(object,str)
    def __init__(self,parent=None):
        super().__init__(parent);self.token=0;self.pool=QThreadPool(self);self.pool.setMaxThreadCount(1);self.signals=PreviewSignals();self.signals.done.connect(self.delivered)
    def clear(self):self.token+=1;self.pool.clear()
    def request(self,path,size):
        self.clear();self.pool.start(Decode(self.token,path,size,self.signals))
    @Slot(int,object,str)
    def delivered(self,token,img,message):
        if token==self.token:self.ready.emit(img,message)
