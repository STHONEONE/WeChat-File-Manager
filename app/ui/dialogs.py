from PySide6.QtCore import QDate,Signal,Qt
from PySide6.QtWidgets import QWidget,QHBoxLayout,QCheckBox,QDateEdit,QDialog,QVBoxLayout,QListWidget,QPushButton,QInputDialog,QMessageBox,QLabel,QPlainTextEdit


class ScanIssueDialog(QDialog):
    def __init__(self,title,summary,errors,parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        available=(parent or self).screen().availableGeometry()
        self.setFixedWidth(min(480,available.width()-32))
        layout=QVBoxLayout(self)
        message=QLabel(summary)
        message.setTextFormat(Qt.TextFormat.PlainText)
        message.setWordWrap(True)
        layout.addWidget(message)
        self.details=QPlainTextEdit()
        self.details.setAccessibleName('扫描异常详情')
        self.details.setReadOnly(True)
        self.details.setPlainText('\n\n'.join(errors))
        self.details.setFixedHeight(min(200,max(72,available.height()//2-35)))
        layout.addWidget(self.details)
        self.details.hide()
        actions=QHBoxLayout()
        layout.addLayout(actions)
        self.toggle_button=QPushButton('查看详情')
        self.toggle_button.setCheckable(True)
        self.toggle_button.setAutoDefault(False)
        self.toggle_button.toggled.connect(self.toggle_details)
        actions.addWidget(self.toggle_button)
        actions.addStretch()
        close=QPushButton('关闭')
        close.setDefault(True)
        close.clicked.connect(self.accept)
        actions.addWidget(close)
        self.adjustSize()

    def toggle_details(self,show):
        self.details.setVisible(show)
        self.toggle_button.setText('收起详情' if show else '查看详情')
        self.adjustSize()

class DateFilter(QWidget):
    textChanged=Signal(str)
    def __init__(self,label):
        super().__init__();layout=QHBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.enabled=QCheckBox(label);self.date=QDateEdit(QDate.currentDate());self.date.setCalendarPopup(True);self.date.setDisplayFormat('yyyy-MM-dd');self.date.setEnabled(False)
        layout.addWidget(self.enabled);layout.addWidget(self.date)
        self.enabled.toggled.connect(self.changed);self.date.dateChanged.connect(self.changed)
    def changed(self,*args):self.date.setEnabled(self.enabled.isChecked());self.textChanged.emit(self.text())
    def text(self):return self.date.date().toString('yyyy-MM-dd') if self.enabled.isChecked() else ''
    def setText(self,text):
        if text:
            d=QDate.fromString(text,'yyyy-MM-dd')
            if not d.isValid():raise ValueError('无效日期')
            self.date.setDate(d)
        self.enabled.setChecked(bool(text))
    def clear(self):self.enabled.setChecked(False)

class TagDialog(QDialog):
    tagSelected=Signal(str)
    def __init__(self,store,parent=None):
        super().__init__(parent);self.store=store;self.setWindowTitle('标签管理中心');self.resize(440,420)
        layout=QVBoxLayout(self);self.list=QListWidget();layout.addWidget(self.list)
        row=QHBoxLayout();layout.addLayout(row)
        for title,handler in [('新建',self.create),('重命名',self.rename),('删除',self.delete),('查看文件',self.choose)]:
            b=QPushButton(title);b.clicked.connect(handler);row.addWidget(b)
        self.list.itemDoubleClicked.connect(self.choose);self.refresh()
    def refresh(self):
        self.list.clear()
        from PySide6.QtCore import Qt
        for tag,count in sorted(self.store.tags().items()):
            self.list.addItem(f'{tag} ({count:,})');self.list.item(self.list.count()-1).setData(Qt.ItemDataRole.UserRole,tag)
    def current(self):
        from PySide6.QtCore import Qt
        return self.list.currentItem().data(Qt.ItemDataRole.UserRole) if self.list.currentItem() else None
    def create(self):
        name,ok=QInputDialog.getText(self,'新建标签','标签名称')
        if ok:
            try:self.store.create_tag(name);self.refresh()
            except ValueError as e:QMessageBox.warning(self,'标签无效',str(e))
    def rename(self):
        old=self.current()
        if old is None:return
        new,ok=QInputDialog.getText(self,'重命名标签','新名称（同名标签将合并）',text=old)
        if ok:
            try:self.store.rename_tag(old,new);self.refresh()
            except ValueError as e:QMessageBox.warning(self,'标签无效',str(e))
    def delete(self):
        name=self.current()
        if name and QMessageBox.question(self,'删除标签',f'删除“{name}”及其文件关联？源文件保持不变。')==QMessageBox.StandardButton.Yes:self.store.delete_tag(name);self.refresh()
    def choose(self,*args):
        name=self.current()
        if name is not None:self.tagSelected.emit(name);self.accept()
