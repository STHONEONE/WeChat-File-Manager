from datetime import datetime
from PySide6.QtCore import Qt,Signal,QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QComboBox,QCheckBox,QTreeWidget,QTreeWidgetItem,QTableView,QFileDialog,QMessageBox
from app.paths import human
from app.ui.file_model import FilesModel

def locate(path):
    import os,sys,subprocess
    from pathlib import Path
    if sys.platform=='win32' and Path(path).is_file():subprocess.Popen(['explorer.exe','/select,',os.path.normpath(path)])
    else:QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

def open_path(path,parent):
    from pathlib import Path
    p=Path(path)
    if not p.is_file():QMessageBox.warning(parent,'文件不可用','文件已不存在或无法访问，请刷新索引。');return
    if p.suffix.lower() in {'.exe','.bat','.cmd','.ps1','.vbs','.js','.msi','.scr','.com','.lnk'}:
        if QMessageBox.question(parent,'运行文件','此文件是程序或脚本，是否调用系统打开？')!=QMessageBox.StandardButton.Yes:return
    if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(p))):QMessageBox.warning(parent,'打开失败','请检查系统文件关联。')

class DuplicatesDialog(QDialog):
    copyRequested=Signal(list)
    recycleRequested=Signal(list)
    def __init__(self,store,detect,cancel,parent=None):
        super().__init__(parent);self.store=store;self.setWindowTitle('重复文件 · 手动选择后移入回收站');self.resize(1120,760);self.group_rows=[]
        layout=QVBoxLayout(self);self.summary=QLabel();self.summary.setWordWrap(True);layout.addWidget(self.summary)
        actions=QHBoxLayout();layout.addLayout(actions)
        for label,callback in [('开始检测',detect),('取消检测',cancel),('刷新结果',self.refresh)]:
            b=QPushButton(label);b.clicked.connect(callback);actions.addWidget(b)
        self.order=QComboBox();self.order.addItems(['理论冗余容量','重复数量','总大小']);actions.addWidget(self.order)
        self.cross=QCheckBox('只看跨账号重复');actions.addWidget(self.cross)
        self.groups=QTreeWidget();self.groups.setHeaderLabels(['SHA-256 组','单份大小','份数','账号数','总大小','理论冗余']);layout.addWidget(self.groups,1)
        more=QPushButton('加载更多重复组');more.clicked.connect(self.load_groups);layout.addWidget(more)
        self.model=FilesModel();self.model.checkable=True;self.members=QTableView();self.members.setModel(self.model);self.members.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows);self.members.setSelectionMode(QTableView.SelectionMode.ExtendedSelection);self.members.setColumnWidth(0,350);layout.addWidget(self.members,1)
        self.path=QLabel('选择文件查看原始路径');self.path.setWordWrap(True);self.path.setTextFormat(Qt.TextFormat.PlainText);self.path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse);layout.addWidget(self.path)
        buttons=QHBoxLayout();layout.addLayout(buttons)
        for label,callback in [('更多组内文件',self.load_members),('打开文件',self.open_selected),('定位文件',self.locate_selected),('复制路径',self.copy_path),('复制归档所选',self.copy_selected)]:
            b=QPushButton(label);b.clicked.connect(callback);buttons.addWidget(b)
        recycle=QPushButton('移入回收站（仅手动勾选项）');recycle.clicked.connect(lambda:self.recycleRequested.emit(self.model.checked_rows()) if self.model.checked_rows() else QMessageBox.information(self,'手动勾选','请在文件名旁明确勾选需要处理的文件，不会自动选择重复项。'));buttons.addWidget(recycle)
        self.groups.itemSelectionChanged.connect(self.group_changed);self.members.selectionModel().selectionChanged.connect(self.member_changed);self.members.doubleClicked.connect(self.open_selected)
        self.order.currentIndexChanged.connect(self.refresh);self.cross.toggled.connect(self.refresh);self.refresh()

    def refresh(self,*args):
        s=self.store.duplicate_summary();state=s['state'];self.groups.clear();self.group_rows=[];self.model.replace([])
        stamp=datetime.fromtimestamp(state['time']).strftime('%Y-%m-%d %H:%M:%S') if state.get('time') else '尚未检测'
        status='检测中' if state.get('running') else '当前索引的候选检测完整' if state.get('complete') else '未完成检测 / 有跳过项'
        self.summary.setText(f'已确认 {s["groups"]:,} 组、{s["files"]:,} 个文件；理论冗余 {human(s["redundant"])}。{status}；{stamp}。\n理论冗余不是已释放空间。微信原始附件可能分别被不同聊天引用，必须手动勾选并额外确认风险，执行前重新校验哈希；不自动选择或永久删除。')
        if not self.store.setting('state:scan',{}).get('complete'):self.summary.setText(self.summary.text()+'\n完整扫描尚未成功或存在访问异常，当前结果不能代表全部微信文件。')
        self.load_groups()

    def load_groups(self):
        rows=self.store.duplicate_groups(['redundant','count','total'][self.order.currentIndex()],self.cross.isChecked(),offset=len(self.group_rows))
        for row in rows:
            item=QTreeWidgetItem(self.groups,[row['sha256'][:16]+'…',human(row['size']),str(row['count']),str(row['accounts']),human(row['total']),human(row['redundant'])]);item.setData(0,Qt.ItemDataRole.UserRole,row)
        self.group_rows.extend(rows)

    def group_changed(self):
        self.model.replace([]);self.path.setText('选择组内文件查看原始路径');self.load_members()

    def load_members(self):
        selected=self.groups.selectedItems()
        if not selected:return
        group=selected[0].data(0,Qt.ItemDataRole.UserRole)
        rows=self.store.duplicate_members(group['sha256'],group['size'],offset=len(self.model.rows))
        self.model.replace(self.model.rows+rows)

    def selected(self):return [self.model.rows[i.row()] for i in self.members.selectionModel().selectedRows()]
    def member_changed(self,*args):
        rows=self.selected()
        if rows:self.path.setText(rows[0]['path'])
    def open_selected(self,*args):
        rows=self.selected()
        if rows:open_path(rows[0]['path'],self)
    def locate_selected(self):
        rows=self.selected()
        if rows:locate(rows[0]['path'])
    def copy_path(self):
        from PySide6.QtWidgets import QApplication
        rows=self.selected()
        if rows:QApplication.clipboard().setText('\n'.join(r['path'] for r in rows))
    def copy_selected(self):
        rows=self.selected()
        if rows:self.copyRequested.emit(rows)
        else:QMessageBox.information(self,'选择文件','请先选择需要归档的组内文件。')
