from datetime import datetime
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QLabel,QTreeWidget,QTreeWidgetItem,QCheckBox,QDialogButtonBox,QPushButton
from app.paths import human

RESULT_LABELS={'pending':'执行中 / 待核对','success':'已移入回收站','failed':'失败','skipped':'跳过','cancelled':'已取消','uncertain':'需核对回收站'}

class DeleteDialog(QDialog):
    def __init__(self,plan,parent=None):
        super().__init__(parent);self.plan=plan;self.setWindowTitle('确认移入 Windows 回收站');self.resize(1050,650)
        layout=QVBoxLayout(self);allowed=[i for i in plan.items if i.allowed]
        summary=QLabel(f'明确选择 {len(plan.items)} 个文件；可进入流程 {len(allowed)} 个；预计回收站接收 {human(sum(i.size for i in allowed))}。\n涉及账号：'+', '.join(sorted({i.account_name for i in plan.items}))+'.\n容量不是已释放空间。失败时不永久删除；禁止项目将跳过；执行前还会重新检查文件状态。')
        summary.setWordWrap(True);summary.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(summary)
        self.list=QTreeWidget();self.list.setHeaderLabels(['文件','大小','账号','原始路径','预检查']);layout.addWidget(self.list)
        from pathlib import Path
        for i in plan.items:
            item=QTreeWidgetItem(self.list,[Path(i.path).name,human(i.size),i.account_name,i.path,'可检查执行' if i.allowed else i.reason]);item.setToolTip(3,i.path);item.setToolTip(4,i.reason)
        self.list.setColumnWidth(3,420)
        self.selected_ack=QCheckBox('我确认仅处理以上清单中的文件。');layout.addWidget(self.selected_ack)
        warning=QLabel('这些是微信管理的原始文件，不同聊天可能分别引用各路径。内容相同也不表示可以安全删除其他路径；移入回收站后，微信可能无法打开对应附件。');warning.setWordWrap(True);layout.addWidget(warning)
        self.original_ack=QCheckBox('我已了解原始附件的路径引用风险，仍确认移入回收站。')
        self.original_ack.setStyleSheet('QCheckBox { color:#9b4025; }');layout.addWidget(self.original_ack)
        note=QLabel('重复文件不会自动勾选；本轮没有“自动保留一份”功能。请自行判断需要保留的原始路径。');note.setWordWrap(True);layout.addWidget(note)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);self.confirm=buttons.button(QDialogButtonBox.StandardButton.Ok);self.confirm.setText('仅移入回收站');self.confirm.setEnabled(False);layout.addWidget(buttons)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject)
        def changed():self.confirm.setEnabled(bool(allowed) and self.selected_ack.isChecked() and self.original_ack.isChecked())
        self.selected_ack.toggled.connect(changed);self.original_ack.toggled.connect(changed)

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
