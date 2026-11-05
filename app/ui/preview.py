"""Image decoding runs off the UI thread and stale results are discarded."""
from pathlib import Path
from PySide6.QtCore import QObject,QRunnable,QThreadPool,Signal,Slot,QSize,Qt
from PySide6.QtGui import QImageReader

class PreviewSignals(QObject):
    done=Signal(int,object,str)

class Decode(QRunnable):
    def __init__(self,token,path,size,signals,documents=False):
        super().__init__();self.token=token;self.path=path;self.size=size;self.signals=signals;self.documents=documents
    def run(self):
        try:
            if self.documents:
                extension=Path(self.path).suffix.lower()
                if extension in {'.txt','.md','.csv'}:
                    with open(self.path,'rb') as stream: data=stream.read(65537)
                    data,truncated=data[:65536],len(data)>65536
                    encoding='utf-16' if data.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig'
                    try:text=data.decode(encoding)
                    except UnicodeDecodeError:text=data.decode('gb18030',errors='replace')
                    self.signals.done.emit(self.token,text+('\n…（仅预览开头）' if truncated else ''),'')
                    return
                if extension=='.pdf':
                    self.preview_pdf()
                    return
            reader=QImageReader(self.path);size=reader.size()
            if self.size>40*1024**2 or size.width()*size.height()>60_000_000:
                self.signals.done.emit(self.token,None,'图片过大，请使用系统程序打开');return
            size.scale(QSize(640,480),Qt.AspectRatioMode.KeepAspectRatio);reader.setScaledSize(size);reader.setAutoTransform(True)
            img=reader.read();self.signals.done.emit(self.token,img,'' if not img.isNull() else '无法预览此图片，请使用系统程序打开')
        except Exception as e:self.signals.done.emit(self.token,None,'预览失败：'+str(e))

    def preview_pdf(self):
        if self.size>40*1024**2:
            self.signals.done.emit(self.token,None,'PDF 较大，请打开文件查看。')
            return
        from PySide6.QtPdf import QPdfDocument
        pdf=QPdfDocument(None)
        pdf.load(self.path)
        if pdf.pageCount():
            size=pdf.pagePointSize(0).toSize()
            size.scale(QSize(520,650),Qt.AspectRatioMode.KeepAspectRatio)
            image=pdf.render(0,size)
            if not image.isNull():
                self.signals.done.emit(self.token,image,'')
                return
        self.signals.done.emit(self.token,None,'无法预览 PDF，请打开文件查看。')

class PreviewController(QObject):
    ready=Signal(object,str)
    def __init__(self,parent=None):
        super().__init__(parent);self.token=0;self.pool=QThreadPool(self);self.pool.setMaxThreadCount(1);self.signals=PreviewSignals();self.signals.done.connect(self.delivered)
    def clear(self):self.token+=1;self.pool.clear()
    def request(self,path,size,documents=False):
        self.clear();self.pool.start(Decode(self.token,path,size,self.signals,documents))
    @Slot(int,object,str)
    def delivered(self,token,img,message):
        if token==self.token:self.ready.emit(img,message)
