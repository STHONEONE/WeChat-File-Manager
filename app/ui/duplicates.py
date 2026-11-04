from PySide6.QtCore import Qt,Signal,QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget,QMenu,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QComboBox,QCheckBox,QTreeWidget,QTreeWidgetItem,QTableView,QMessageBox,QScrollArea,QFrame
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

class DuplicateMembers(FilesModel):
    def __init__(self, page):
        super().__init__()
        self.page = page
        self.checkable = True
        self.columns = [*FilesModel.columns, '清理建议']

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and index.column() == 7:
            if role == Qt.ItemDataRole.DisplayRole:
                return self.page.member_status(self.rows[index.row()])
            return None
        return super().data(index, role)

    def flags(self, index):
        flags = super().flags(index)
        if index.isValid() and not self.page.can_check(self.rows[index.row()]):
            flags &= ~Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or not self.page.can_check(self.rows[index.row()]):
            return False
        if not super().setData(index, value, role):
            return False
        row = self.rows[index.row()]
        self.page.set_checked(row, row['path'] in self.checked_paths)
        return True


class DuplicatesDialog(QWidget):
    """Persistent duplicates page; selections outlive the displayed model rows."""

    copyRequested = Signal(list)
    recycleRequested = Signal(list)
    suggestRequested = Signal()

    def __init__(self, store, detect, cancel, parent=None):
        super().__init__(parent)
        self.store = store
        self.group_rows = []
        self.checked = {}
        self.checked_size = 0
        self.draft = None
        self.complete = False
        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(110)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName('workspace')
        scroll.setWidget(content)
        page_layout.addWidget(scroll, 1)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 4, 0, 0)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        actions = QHBoxLayout()
        layout.addLayout(actions)
        self.button(actions, '检测重复文件', detect)
        self.suggest = self.button(actions, '一键勾选多余副本', lambda: self.suggestRequested.emit())
        self.suggest.setProperty('kind', 'primary')
        self.button(actions, '清空选择', self.clear_selection)
        self.button(actions, '取消任务', cancel)
        actions.addStretch()

        filters = QHBoxLayout()
        layout.addLayout(filters)
        self.order = QComboBox()
        self.order.addItems(['理论冗余容量', '重复数量', '总大小'])
        filters.addWidget(self.order)
        self.cross = QCheckBox('只看跨账号重复')
        filters.addWidget(self.cross)
        filters.addStretch()
        self.more_groups = self.button(filters, '更多重复组', self.load_groups)
        self.groups = QTreeWidget()
        self.groups.setMinimumHeight(45)
        self.groups.setRootIsDecorated(False)
        self.groups.setHeaderLabels(['文件示例', '单份大小', '份数', '所属账号', '理论冗余'])
        self.groups.setColumnWidth(0, 205)
        layout.addWidget(self.groups, 1)

        members_bar = QHBoxLayout()
        layout.addLayout(members_bar)
        self.keeper_button = self.button(members_bar, '将当前文件设为保留项', self.set_keeper)
        self.keeper_button.setEnabled(False)
        members_bar.addStretch()
        self.more_members = self.button(members_bar, '更多组内文件', self.load_members)
        self.model = DuplicateMembers(self)
        self.members = QTableView()
        self.members.setMinimumHeight(45)
        self.members.setModel(self.model)
        self.members.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.members.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self.members.setColumnWidth(0, 200)
        self.members.setColumnWidth(2, 72)
        self.members.setColumnWidth(7, 120)
        self.members.horizontalHeader().moveSection(7, 1)
        for column in (1, 3, 5, 6):
            self.members.setColumnHidden(column, True)
        self.members.verticalHeader().hide()
        layout.addWidget(self.members, 1)
        self.path = QLabel('选择组内文件查看真实路径')
        self.path.setTextFormat(Qt.TextFormat.PlainText)
        self.path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.path.setMinimumWidth(0)
        layout.addWidget(self.path)
        footer = QHBoxLayout()
        page_layout.addLayout(footer)
        self.selection_label = QLabel()
        footer.addWidget(self.selection_label, 1)
        self.recycle = self.button(footer, '预览清理清单', lambda: self.recycleRequested.emit(list(self.checked.values())))
        self.recycle.setProperty('kind', 'danger')
        self.groups.itemSelectionChanged.connect(self.group_changed)
        self.members.selectionModel().selectionChanged.connect(self.member_changed)
        self.members.doubleClicked.connect(self.open_selected)
        self.members.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.members.customContextMenuRequested.connect(self.member_menu)
        self.order.currentIndexChanged.connect(self.refresh)
        self.cross.toggled.connect(self.refresh)
        self.refresh()

    @staticmethod
    def button(layout, label, handler):
        button = QPushButton(label)
        button.clicked.connect(handler)
        layout.addWidget(button)
        return button

    def invalidate(self):
        self.draft = None
        self.clear_selection()
        self.refresh()

    def refresh(self, *args):
        key = self.group_key()
        summary = self.store.duplicate_summary()
        state = summary['state']
        self.complete = bool(state.get('complete') and not state.get('running'))
        if self.draft and (not self.complete or self.draft.stamp != state.get('time')):
            self.draft = None
            self.clear_selection()
        status = '检测结果可用' if self.complete else '请检测或重新检测重复文件'
        self.summary.setText(
            f'已确认 {summary["groups"]:,} 组  ·  {summary["files"]:,} 个文件  ·  '
            f'理论冗余 {human(summary["redundant"])}\n{status}。一键勾选覆盖全部账号，预览后由你确认。'
        )
        self.suggest.setEnabled(self.complete and summary['groups'] > 0)
        limit = len(self.group_rows)
        self.groups.clear()
        self.group_rows = []
        self.load_groups()
        if key:
            while len(self.group_rows) < limit and self.more_groups.isEnabled():
                self.load_groups()
            for i, row in enumerate(self.group_rows):
                if (row['sha256'], row['size']) == key:
                    self.groups.setCurrentItem(self.groups.topLevelItem(i))
                    break
        self.update_selection()

    def load_groups(self):
        rows = self.store.duplicate_groups(
            ['redundant', 'count', 'total'][self.order.currentIndex()],
            self.cross.isChecked(), offset=len(self.group_rows))
        for row in rows:
            accounts = row['sample_account'] or '未知账号'
            if row['accounts'] > 1:
                accounts += f' 等 {row["accounts"]} 个账号'
            item = QTreeWidgetItem(self.groups, [
                row['sample_name'], human(row['size']), str(row['count']),
                accounts, human(row['redundant'])])
            item.setToolTip(0, row['sha256'])
            item.setData(0, Qt.ItemDataRole.UserRole, row)
        self.group_rows.extend(rows)
        self.more_groups.setEnabled(len(rows) == 200)

    def group_key(self):
        item = self.groups.currentItem()
        if item:
            group = item.data(0, Qt.ItemDataRole.UserRole)
            return group['sha256'], group['size']
        return None

    def group_changed(self):
        self.model.replace([])
        self.path.setText('选择组内文件查看真实路径')
        self.load_members()

    def load_members(self):
        key = self.group_key()
        rows = self.store.duplicate_members(*key, offset=len(self.model.rows)) if key else []
        self.model.replace(self.model.rows + rows)
        self.more_members.setEnabled(len(rows) == 200)
        self.sync_checks()

    def sync_checks(self):
        self.model.checked_paths = {row['path'] for row in self.model.rows if row['path'] in self.checked}
        if self.model.rows:
            self.model.dataChanged.emit(self.model.index(0, 0),
                                        self.model.index(len(self.model.rows) - 1, 7))
        self.update_selection()
        self.member_changed()

    def apply_suggestions(self, draft):
        if self.draft and self.draft.stamp == draft.stamp:
            for group, path in self.draft.keepers.items():
                if path in draft.eligible:
                    draft.keepers[group] = path
        self.draft = draft
        self.checked = draft.suggestions()
        self.checked_size = sum(row['size'] for row in self.checked.values())
        self.sync_checks()

    def clear_selection(self):
        self.checked.clear()
        self.checked_size = 0
        self.sync_checks()

    def set_checked(self, row, checked):
        path = row['path']
        if checked and path not in self.checked:
            self.checked[path] = row
            self.checked_size += row['size']
        elif not checked and path in self.checked:
            self.checked_size -= self.checked.pop(path)['size']
        self.update_selection()

    def can_check(self, row):
        if not self.draft:
            from app.directory_mapper import deletion_path_allowed
            return self.complete and deletion_path_allowed(row['path'], row['account'])
        return row['path'] in self.draft.eligible and self.draft.keepers.get(self.group_key()) != row['path']

    def member_status(self, row):
        if not self.draft:
            return '待检查' if self.can_check(row) else '不可清理'
        path = row['path']
        if path not in self.draft.eligible:
            return '待核对 / 不可清理'
        return '建议清理' if self.can_check(row) else '建议保留'

    def update_selection(self):
        self.selection_label.setText(f'已勾选 {len(self.checked):,} 个文件  ·  {human(self.checked_size)}')
        self.recycle.setEnabled(self.complete and bool(self.checked))

    def set_keeper(self):
        rows = self.selected()
        if not self.draft or len(rows) != 1 or rows[0]['path'] not in self.draft.eligible:
            return
        path = rows[0]['path']
        key = self.group_key()
        previous = self.draft.keepers[key]
        if previous == path:
            return
        if self.checked.pop(path, None):
            self.checked[previous] = self.draft.eligible[previous]
        self.draft.keepers[key] = path
        self.sync_checks()

    def selected(self):
        return [self.model.rows[i.row()] for i in self.members.selectionModel().selectedRows()]

    def member_changed(self, *args):
        rows = self.selected()
        self.keeper_button.setEnabled(bool(self.draft and len(rows) == 1 and rows[0]['path'] in self.draft.eligible))
        if rows:
            path = rows[0]['path']
            reason = self.draft.blocked.get(path, '') if self.draft else ''
            text = (reason + ' · ' if reason else '') + path
            self.path.setToolTip(text)
            self.path.setText(self.path.fontMetrics().elidedText(text, Qt.TextElideMode.ElideMiddle, max(100, self.width() - 12)))

    def member_menu(self, position):
        rows = self.selected()
        if not rows:
            return
        from PySide6.QtWidgets import QApplication
        menu = QMenu(self)
        menu.addAction('打开文件', self.open_selected)
        menu.addAction('打开所在文件夹', lambda: locate(rows[0]['path']))
        menu.addAction('复制路径', lambda: QApplication.clipboard().setText('\n'.join(row['path'] for row in rows)))
        menu.addAction('复制归档所选', lambda: self.copyRequested.emit(rows))
        menu.exec(self.members.viewport().mapToGlobal(position))

    def open_selected(self, *args):
        rows = self.selected()
        if rows:
            open_path(rows[0]['path'], self)
