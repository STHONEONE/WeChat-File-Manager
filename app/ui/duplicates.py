from pathlib import Path

from PySide6.QtCore import Qt, Signal, QUrl, QSignalBlocker
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (QApplication, QFrame, QHeaderView, QHBoxLayout, QLabel, QMenu,
                               QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSplitter,
                               QSizePolicy, QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from app.directory_mapper import deletion_path_allowed
from app.paths import human
from app.ui.preview import PreviewController


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

class NameMatchesPage(QWidget):
    recycleRequested = Signal(list)
    role = Qt.ItemDataRole.UserRole

    def __init__(self, detect, parent=None):
        super().__init__(parent)
        self.matches = []
        self.visible_members = {}
        self.checked = {}
        self.checked_size = 0
        self.current_row = None
        self.preview_image = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        toolbar = QHBoxLayout()
        layout.addLayout(toolbar)
        self.detect_button = QPushButton('查相近名称')
        self.detect_button.setProperty('kind', 'primary')
        self.detect_button.clicked.connect(detect)
        toolbar.addWidget(self.detect_button)
        toolbar.addStretch()
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        splitter = QSplitter()
        layout.addWidget(splitter, 1)
        self.groups = QTreeWidget()
        self.groups.setMinimumHeight(60)
        self.groups.setHeaderLabels(['文件 / 名称相近组', '大小'])
        self.groups.setAlternatingRowColors(True)
        self.groups.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.groups.setColumnWidth(1, 76)
        splitter.addWidget(self.groups)

        details = QWidget()
        details.setMinimumWidth(170)
        panel = QVBoxLayout(details)
        panel.setContentsMargins(8, 0, 0, 0)
        panel.addWidget(QLabel('文件预览'))
        self.details = QLabel('展开一组，选择要查看的文件。')
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        self.details.setWordWrap(True)
        panel.addWidget(self.details)
        self.preview_stack = QStackedWidget()
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setWordWrap(True)
        self.preview.setMinimumSize(90, 45)
        self.preview.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Ignored)
        self.preview_stack.addWidget(self.preview)
        self.text_preview = QPlainTextEdit()
        self.text_preview.setReadOnly(True)
        self.text_preview.setAccessibleName('文本文件预览')
        self.preview_stack.addWidget(self.text_preview)
        panel.addWidget(self.preview_stack, 1)
        self.path = QPlainTextEdit()
        self.path.setReadOnly(True)
        self.path.setFixedHeight(48)
        self.path.setAccessibleName('当前文件的完整路径')
        panel.addWidget(self.path)
        self.open_button = QPushButton('打开文件')
        self.open_button.clicked.connect(self.open_current)
        panel.addWidget(self.open_button)
        detail_scroll = QScrollArea()
        detail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setMinimumHeight(80)
        detail_scroll.setMinimumWidth(175)
        detail_scroll.setWidget(details)
        splitter.addWidget(detail_scroll)
        splitter.setCollapsible(1, False)
        splitter.setSizes([570, 290])

        footer = QHBoxLayout()
        layout.addLayout(footer)
        self.more_button = QPushButton('更多文件组')
        self.more_button.clicked.connect(self.load_groups)
        footer.addWidget(self.more_button)
        self.selection_label = QLabel()
        footer.addWidget(self.selection_label, 1)
        self.clear_button = QPushButton('清空勾选')
        self.clear_button.clicked.connect(self.clear_selection)
        footer.addWidget(self.clear_button)
        self.recycle_button = QPushButton()
        self.recycle_button.setProperty('kind', 'danger')
        self.recycle_button.clicked.connect(self.preview_cleanup)
        footer.addWidget(self.recycle_button)

        self.decoder = PreviewController(self)
        self.decoder.ready.connect(self.preview_ready)
        self.groups.itemExpanded.connect(self.expand_group)
        self.groups.currentItemChanged.connect(self.show_current)
        self.groups.itemChanged.connect(self.check_changed)
        self.groups.itemActivated.connect(self.activate_item)
        self.groups.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.groups.customContextMenuRequested.connect(self.file_menu)
        self.set_results([], '点击「查相近名称」，按文件名前缀查找。')

    def set_results(self, groups, summary):
        self.matches = groups
        self.summary.setText(summary)
        self.groups.clear()
        self.visible_members.clear()
        self.clear_selection()
        self.show_current(None)
        self.load_groups()
        if groups:
            self.groups.setCurrentItem(self.groups.topLevelItem(0))
            self.groups.topLevelItem(0).setExpanded(True)

    def invalidate(self):
        self.set_results([], '索引已更新，请重新查找相近名称。')

    def load_groups(self):
        offset = self.groups.topLevelItemCount()
        for rows in self.matches[offset:offset + 150]:
            group = QTreeWidgetItem(self.groups, [f'{rows[0]["name"]} · {len(rows):,} 个文件',
                                                 human(sum(row['size'] for row in rows))])
            group.setData(0, self.role, rows)
            group.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
        self.more_button.setVisible(self.groups.topLevelItemCount() < len(self.matches))

    def expand_group(self, item):
        if item.parent() is None and item.childCount() == 0:
            self.load_members(item)

    def load_members(self, group):
        rows = group.data(0, self.role)
        offset = group.childCount()
        tail = group.child(offset - 1) if offset else None
        if tail and tail.data(0, self.role) is None:
            group.takeChild(offset - 1)
            offset -= 1
        with QSignalBlocker(self.groups):
            for row in rows[offset:offset + 150]:
                child = QTreeWidgetItem(group, [row['name'], human(row['size'])])
                child.setData(0, self.role, row)
                child.setToolTip(0, row['path'])
                if deletion_path_allowed(row['path'], row['account']):
                    child.setCheckState(0, Qt.CheckState.Checked if row['path'] in self.checked else Qt.CheckState.Unchecked)
                    self.visible_members.setdefault(row['path'], []).append(child)
                else:
                    child.setFlags(child.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                    child.setToolTip(0, '仅查看 · ' + row['path'])
            if offset + 150 < len(rows):
                QTreeWidgetItem(group, ['双击加载本组更多文件…'])

    def check_changed(self, item, column):
        row = item.data(0, self.role) if item.parent() and column == 0 else None
        if not row or not deletion_path_allowed(row['path'], row['account']):
            return
        path = row['path']
        state = item.checkState(0)
        if state == Qt.CheckState.Checked and path not in self.checked:
            self.checked[path] = row
            self.checked_size += row['size']
        elif state != Qt.CheckState.Checked and path in self.checked:
            self.checked_size -= self.checked.pop(path)['size']
        with QSignalBlocker(self.groups):
            for other in self.visible_members[path]:
                if other is not item:
                    other.setCheckState(0, state)
        self.update_selection()

    def clear_selection(self):
        with QSignalBlocker(self.groups):
            for path in self.checked:
                for item in self.visible_members.get(path, ()):
                    item.setCheckState(0, Qt.CheckState.Unchecked)
        self.checked.clear()
        self.checked_size = 0
        self.update_selection()

    def update_selection(self):
        count = len(self.checked)
        self.selection_label.setText(f'已勾选 {count:,} 项 · {human(self.checked_size)}')
        self.clear_button.setEnabled(bool(count))
        self.recycle_button.setEnabled(bool(count))
        self.recycle_button.setText(f'预览删除 {count:,} 项' if count else '预览删除')

    def preview_cleanup(self):
        if self.checked:
            self.recycleRequested.emit(list(self.checked.values()))

    def show_current(self, item, previous=None):
        self.decoder.clear()
        row = item.data(0, self.role) if item and item.parent() else None
        self.current_row = row
        self.preview_image = None
        self.preview_stack.setCurrentIndex(0)
        self.preview.clear()
        self.open_button.setEnabled(bool(row))
        self.path.setPlainText(row['path'] if row else '')
        if not row:
            self.details.setText('展开一组，选择要查看的文件。')
            if item and item.parent() is None:
                item.setExpanded(True)
            return
        self.details.setText(f'{row["name"]}\n{row["account_name"]} · {human(row["size"])}')
        extension = Path(row['name']).suffix.lower()
        if row['category'] == '图片' or extension in {'.pdf', '.txt', '.md', '.csv'}:
            self.preview.setText('正在读取预览…')
            self.decoder.request(row['path'], row['size'], documents=True)
        else:
            self.preview.setText('点击下方「打开文件」查看内容。')

    def preview_ready(self, result, message):
        if isinstance(result, str):
            self.text_preview.setPlainText(result)
            self.preview_stack.setCurrentIndex(1)
        elif message:
            self.preview.setText(message)
        elif result is not None:
            self.preview_image = result
            self.update_image()

    def update_image(self):
        if self.preview_image is not None:
            self.preview.setPixmap(QPixmap.fromImage(self.preview_image).scaled(
                self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_image()

    def activate_item(self, item, column):
        if item.parent() and item.data(0, self.role) is None:
            self.load_members(item.parent())
        elif item.parent():
            self.open_current()
        else:
            item.setExpanded(not item.isExpanded())

    def open_current(self):
        if self.current_row:
            open_path(self.current_row['path'], self)

    def file_menu(self, position):
        item = self.groups.itemAt(position)
        row = item.data(0, self.role) if item and item.parent() else None
        if not row:
            return
        path = row['path']
        menu = QMenu(self)
        menu.addAction('打开文件', lambda: open_path(path, self))
        menu.addAction('打开所在文件夹', lambda: locate(path))
        menu.addAction('复制完整路径', lambda: QApplication.clipboard().setText(path))
        menu.exec(self.groups.viewport().mapToGlobal(position))
