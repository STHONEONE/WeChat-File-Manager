from datetime import datetime
from pathlib import Path
from PySide6.QtCore import Qt,QAbstractTableModel,QModelIndex,Signal
from PySide6.QtWidgets import QDialog,QVBoxLayout,QLabel,QTreeWidget,QTreeWidgetItem,QDialogButtonBox,QPushButton,QTableView,QPlainTextEdit
from app.paths import human

RESULT_LABELS={'pending':'执行中 / 待核对','success':'已移入回收站','failed':'失败','skipped':'跳过','cancelled':'已取消','uncertain':'需核对回收站'}

class CleanupPreview(QAbstractTableModel):
    changed=Signal()
    columns=['移入回收站','保留文件','大小','账号','预检查']

    def __init__(self,items,parent):
        super().__init__(parent)
        self.items=items
        self.excluded=set()
        self.count=sum(item.allowed for item in items)
        self.size=sum(item.size for item in items if item.allowed)

    def rowCount(self,parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def columnCount(self,parent=QModelIndex()):
        return len(self.columns)

    def headerData(self,section,orientation,role=Qt.ItemDataRole.DisplayRole):
        if orientation==Qt.Orientation.Horizontal and role==Qt.ItemDataRole.DisplayRole:
            return self.columns[section]

    def data(self,index,role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():return None
        item=self.items[index.row()]
        if role==Qt.ItemDataRole.CheckStateRole and index.column()==0:
            return Qt.CheckState.Checked if item.allowed and item.path not in self.excluded else Qt.CheckState.Unchecked
        if role==Qt.ItemDataRole.ToolTipRole and index.column()<2:
            return item.path if index.column()==0 else item.keeper.path if item.keeper else ''
        if role in (Qt.ItemDataRole.DisplayRole,Qt.ItemDataRole.ToolTipRole):
            return (Path(item.path).name,Path(item.keeper.path).name if item.keeper else '',
                    human(item.size),item.account_name,'待确认' if item.allowed else item.reason)[index.column()]

    def flags(self,index):
        flags=super().flags(index)
        if index.isValid() and index.column()==0 and self.items[index.row()].allowed:
            flags|=Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def setData(self,index,value,role=Qt.ItemDataRole.EditRole):
        if role!=Qt.ItemDataRole.CheckStateRole or not self.flags(index)&Qt.ItemFlag.ItemIsUserCheckable:
            return False
        item=self.items[index.row()]
        checked=value in (Qt.CheckState.Checked,Qt.CheckState.Checked.value)
        if checked==(item.path not in self.excluded):return False
        if checked:self.excluded.remove(item.path)
        else:self.excluded.add(item.path)
        self.count+=1 if checked else -1
        self.size+=item.size if checked else -item.size
        self.dataChanged.emit(index,index,[role])
        self.changed.emit()
        return True

class DeleteDialog(QDialog):
    def __init__(self,plan,parent=None):
        super().__init__(parent);self.plan=plan;self.setWindowTitle('预览清理清单')
        available=self.screen().availableGeometry()
        self.resize(min(1000,available.width()-40),min(590,available.height()-55))
        layout=QVBoxLayout(self)
        self.preview_model=CleanupPreview(plan.items,self)
        summary=QLabel()
        summary.setWordWrap(True);summary.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(summary)
        self.list=QTableView();self.list.setMinimumHeight(65);self.list.setModel(self.preview_model);layout.addWidget(self.list,1)
        self.list.verticalHeader().hide()
        self.list.setColumnWidth(0,170);self.list.setColumnWidth(1,155);self.list.setColumnWidth(2,72)
        self.list.setColumnHidden(1,not any(item.keeper for item in plan.items))
        self.paths=QPlainTextEdit()
        self.paths.setReadOnly(True);self.paths.setFixedHeight(64)
        self.paths.setAccessibleName('所选行的完整路径')
        self.paths.setPlaceholderText('选中一行查看完整路径')
        layout.addWidget(self.paths)
        self.list.selectionModel().currentChanged.connect(self.show_paths)
        if plan.items:self.list.setCurrentIndex(self.preview_model.index(0,0))
        warning=QLabel('移入回收站后，微信可能无法打开对应聊天附件。请核对勾选的文件。')
        warning.setWordWrap(True);layout.addWidget(warning)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);self.confirm=buttons.button(QDialogButtonBox.StandardButton.Ok);self.confirm.setText('移入回收站');self.confirm.setProperty('kind','danger');layout.addWidget(buttons)
        cancel=buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setText('取消');cancel.setDefault(True);cancel.setFocus()
        self.confirm.setAutoDefault(False)
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject)
        accounts=sorted({item.account_name for item in plan.items})
        account_text='、'.join(accounts[:4])
        if len(accounts)>4:account_text+=f' 等 {len(accounts)} 个账号'
        def changed():
            summary.setText(f'计划 {len(plan.items):,} 项 · 已勾选 {self.preview_model.count:,} 项 · 预计接收 {human(self.preview_model.size)}\n涉及账号 {account_text}。可在列表中取消个别勾选。')
            self.confirm.setEnabled(bool(self.preview_model.count))
        self.preview_model.changed.connect(changed)
        changed()

    def excluded_paths(self):
        return frozenset(self.preview_model.excluded)

    def show_paths(self,current,previous):
        if not current.isValid():return
        item=self.plan.items[current.row()]
        text=f'待回收：{item.path}'
        if item.keeper:text=f'保留：{item.keeper.path}\n'+text
        self.paths.setPlainText(text)

class DeleteHistoryDialog(QDialog):
    def __init__(self,service,parent=None):
        super().__init__(parent);self.service=service;self.offset=0;self.setWindowTitle('本机删除记录');self.resize(1100,650)
        layout=QVBoxLayout(self);label=QLabel('记录仅用于核对，不保证自动恢复。pending / uncertain 项请自行核对原路径与 Windows 回收站。');label.setWordWrap(True);layout.addWidget(label)
        self.table=QTreeWidget();self.table.setHeaderLabels(['时间','原始路径','大小','结果','原因','重复组 SHA-256']);layout.addWidget(self.table)
        more=QPushButton('加载更多记录');more.clicked.connect(self.load);layout.addWidget(more);self.load()
    def load(self):
        rows=self.service.history(offset=self.offset)
        for row in rows:QTreeWidgetItem(self.table,[datetime.fromtimestamp(row['time']).strftime('%Y-%m-%d %H:%M:%S'),row['path'],human(row['size']),RESULT_LABELS.get(row['result'],row['result']),row['reason'],row['sha256'] or '普通文件'])
        self.offset+=len(rows)
