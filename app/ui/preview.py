"""Image decoding runs off the UI thread and stale results are discarded."""
from pathlib import Path
from PySide6.QtCore import QObject,QRunnable,QThreadPool,Signal,Slot,QSize,Qt,QTimer,QUrl
from PySide6.QtGui import QImageReader
from app.office_preview import OFFICE_PREVIEW_EXTENSIONS, office_preview

TEXT_EXTENSIONS={'.txt','.md','.csv'}
DOCUMENT_PREVIEW_EXTENSIONS=OFFICE_PREVIEW_EXTENSIONS|TEXT_EXTENSIONS|{'.pdf'}

def supports_preview(path,category):
    return category in {'图片','视频'} or Path(path).suffix.lower() in DOCUMENT_PREVIEW_EXTENSIONS

class PreviewSignals(QObject):
    done=Signal(int,object,str)

class Decode(QRunnable):
    def __init__(self,token,path,size,signals,documents=False):
        super().__init__();self.token=token;self.path=path;self.size=size;self.signals=signals;self.documents=documents
    def run(self):
        try:
            if self.documents:
                extension=Path(self.path).suffix.lower()
                if extension in TEXT_EXTENSIONS:
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
                if extension in OFFICE_PREVIEW_EXTENSIONS:
                    result=office_preview(self.path)
                    self.signals.done.emit(self.token,result,'' if result is not None else '没有可提取的封面，请打开文件查看。')
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
        self.player=None
    def clear(self):
        self.token+=1;self.pool.clear()
        self.stop_video()
    def request(self,path,size,documents=False):
        self.clear();self.pool.start(Decode(self.token,path,size,self.signals,documents))
    def request_file(self,path,size,category):
        if category=='视频':
            self.request_video(path)
        else:
            self.request(path,size,documents=True)
    def request_video(self,path):
        self.clear()
        try:
            from PySide6.QtMultimedia import QMediaPlayer,QVideoSink
        except ImportError:
            self.ready.emit(None,'视频预览不可用，请打开文件播放。')
            return
        token=self.token
        player=QMediaPlayer(self)
        sink=QVideoSink(player)
        self.player=player
        player.setVideoSink(sink)
        sink.videoFrameChanged.connect(lambda frame:self.video_frame(token,frame))
        player.errorOccurred.connect(lambda *_:self.video_failed(token))
        player.setSource(QUrl.fromLocalFile(path))
        player.play()
        QTimer.singleShot(5500,self,lambda:self.video_failed(token))

    def stop_video(self):
        if self.player is not None:
            player,self.player=self.player,None
            player.stop()
            player.deleteLater()

    def video_frame(self,token,frame):
        if token!=self.token or self.player is None or not frame.isValid():
            return
        image=frame.toImage()
        if not image.isNull():
            self.stop_video()
            self.ready.emit(image,'')

    def video_failed(self,token):
        if token==self.token and self.player is not None:
            self.stop_video()
            self.ready.emit(None,'无法获取视频画面，请打开文件播放。')
    @Slot(int,object,str)
    def delivered(self,token,img,message):
        if token==self.token:self.ready.emit(img,message)
