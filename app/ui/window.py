import json
import os
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QAbstractTableModel, QModelIndex, QSortFilterProxyModel, QIdentityProxyModel, QTimer, QUrl,QObject
from PySide6.QtGui import QDesktopServices, QImageReader, QPixmap, QIcon, QPainter, QColor, QFontDatabase, QFont
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QLineEdit,QComboBox,QPushButton,QSplitter,QTreeWidget,QTreeWidgetItem,QTableView,QLabel,QTextEdit,QCheckBox,QFormLayout,QFileDialog,QMessageBox,QInputDialog,QMenu,QDoubleSpinBox,QDialog,QDialogButtonBox,QProgressBar,QStackedWidget,QGridLayout,QScrollArea,QStyle)
from app.core import Store, CATEGORIES, LABELS, candidates, canonical, human, export_files
from app.version import __version__

class Worker(QThread):
    progress=Signal(str)
    done=Signal(object)
    def __init__(self, fn):
        super().__init__(); self.fn=fn
    def run(self):
        try: self.done.emit({'result':self.fn(self.progress.emit)})
        except Exception as e: self.done.emit({'error':str(e)})

from app.ui.file_model import FilesModel
from app.ui.dialogs import DateFilter,TagDialog
from app.ui.preview import PreviewController
from app.ui.duplicates import NameMatchesPage
from app.ui.statistics_view import StatisticsDialog
from app.file_monitor import FileMonitor
from app.directory_mapper import describe_directory,virtual_sections
from app.delete_service import DeleteService
from app.ui.delete_dialog import DeleteDialog,DeleteHistoryDialog
from app.duplicate_detector import HashCancelled
from app.name_matches import name_groups
from app.snapshots import indexed_signature
from app.ui.styles import WINDOW_STYLE

class MonitorSignals(QObject):
    updated=Signal(object)
    status=Signal(str)

class Window(QMainWindow):
    def __init__(self,store, auto=True):
        super().__init__(); self.store=store; self.worker=None; self.active=None; self.nav={}; self.directory_data={}; self.sort_order='mtime'; self.sort_desc=True
        font=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/'msyh.ttc'
        if font.exists(): QFontDatabase.addApplicationFont(str(font))
        self.setFont(QFont('Microsoft YaHei',10))
        self.setStyleSheet(WINDOW_STYLE)
        self.setWindowTitle('微信文件管理器 '+__version__+' 开发版'); self.resize(1180,760)
        outer=QWidget(); outer.setObjectName('workspace'); self.setCentralWidget(outer)
        shell=QVBoxLayout(outer); shell.setContentsMargins(12,10,12,8)
        header=QHBoxLayout(); shell.addLayout(header)
        title=QLabel('微信文件管理器'); title.setObjectName('brand'); header.addWidget(title)
        header.addStretch()
        self.account=QComboBox(); self.account.setMaximumWidth(190); header.addWidget(self.account)
        self.scan_button=self.button(header,'刷新索引',self.scan)
        self.button(header,'设置',self.settings)
        body=QHBoxLayout(); shell.addLayout(body,1)
        sidebar=QVBoxLayout(); body.addLayout(sidebar)
        self.nav_buttons={}
        for key,label,icon in [('directory','微信目录',QStyle.StandardPixmap.SP_DirIcon),
                               ('duplicates','相近名称',QStyle.StandardPixmap.SP_FileDialogDetailedView),
                               ('search','查找文件',QStyle.StandardPixmap.SP_FileDialogContentsView)]:
            button=self.button(sidebar,label,lambda checked=False,k=key:self.switch_page(k))
            button.setProperty('nav',True);button.setCheckable(True);button.setIcon(self.style().standardIcon(icon))
            self.nav_buttons[key]=button
        more=QPushButton('更多功能');more.setProperty('nav',True);sidebar.addWidget(more)
        menu=QMenu(more)
        menu.addAction('标签管理',self.tag_center)
        menu.addAction('查看收藏',lambda:self.open_collection('favorite'))
        menu.addAction('最近文件',lambda:self.open_collection('recent'))
        menu.addAction('大文件',lambda:self.open_collection('large'))
        menu.addAction('已不存在的文件',lambda:self.open_collection('missing'))
        menu.addSeparator()
        menu.addAction('存储统计',self.statistics)
        menu.addAction('开启 / 关闭自动监控',self.toggle_monitor)
        menu.addAction('设置与备份',self.settings)
        menu.addAction('删除记录',self.show_history)
        more.setMenu(menu);sidebar.addStretch()
        layout=QVBoxLayout();body.addLayout(layout,1)
        toolbar=QHBoxLayout(); layout.addLayout(toolbar)
        self.page_title=QLabel();self.page_title.setObjectName('pageTitle');toolbar.addWidget(self.page_title)
        toolbar.addStretch()
        self.query=QLineEdit(); self.query.setPlaceholderText('搜索文件名、标签或备注');toolbar.addWidget(self.query,1)
        self.query.textEdited.connect(lambda _:self.switch_page('search'))
        self.query.returnPressed.connect(self.reload)
        self.pages=QStackedWidget();layout.addWidget(self.pages,1)
        browser=QWidget();self.pages.addWidget(browser);browser_layout=QVBoxLayout(browser)
        browser_layout.setContentsMargins(0,0,0,0)
        row=QHBoxLayout();browser_layout.addLayout(row)
        self.add_button=self.button(row,'添加微信目录',self.add_root)
        self.category=QComboBox();self.category.addItems(['全部类型',*CATEGORIES,'其他文件']);row.addWidget(self.category)
        self.advanced_button=self.button(row,'高级筛选',lambda:self.filters.setVisible(self.advanced_button.isChecked()))
        self.advanced_button.setCheckable(True)
        row.addStretch()
        self.details_button=self.button(row,'详情',lambda:self.detail_scroll.setVisible(self.details_button.isChecked()))
        self.details_button.setCheckable(True)
        self.edit_selection_button=self.button(row,'编辑选择',self.edit_file_selection)
        self.edit_selection_button.setCheckable(True)
        self.filters=QWidget();browser_layout.addWidget(self.filters)
        filters=QGridLayout(self.filters);filters.setContentsMargins(0,0,0,0)
        self.start=DateFilter('起始日期')
        self.end=DateFilter('结束日期')
        self.minimum=QDoubleSpinBox(); self.minimum.setRange(0,1e9); self.minimum.setSuffix(' MiB 起');self.minimum.setMaximumWidth(150)
        self.maximum=QDoubleSpinBox(); self.maximum.setRange(0,1e9); self.maximum.setSuffix(' MiB 止');self.maximum.setMaximumWidth(150);self.maximum.setToolTip('大小上限；0 表示不限')
        self.tag_filter=QLineEdit(); self.tag_filter.setPlaceholderText('标签筛选');self.tag_filter.setMinimumWidth(120)
        for index,w in enumerate([self.start,self.end,self.minimum,self.maximum,self.tag_filter]):
            filters.addWidget(w,index//2,index%2)
        self.empty_label=QLabel();self.empty_label.setWordWrap(True);browser_layout.addWidget(self.empty_label)
        task=QHBoxLayout();layout.addLayout(task)
        self.progress_label=QLabel('就绪');self.progress_label.setObjectName('taskStatus');self.progress_label.setWordWrap(True);task.addWidget(self.progress_label,1)
        self.progress_bar=QProgressBar();self.progress_bar.setMaximumWidth(90);self.progress_bar.setRange(0,0);self.progress_bar.hide();task.addWidget(self.progress_bar)
        self.stop_button=self.button(task,'停止任务',lambda:self.worker.requestInterruption() if self.worker else None);self.stop_button.hide()
        splitter=QSplitter();browser_layout.addWidget(splitter,1)
        nav_panel=QWidget();self.directory_panel=nav_panel;nav_layout=QVBoxLayout(nav_panel);nav_layout.setContentsMargins(0,0,0,0)
        self.directory_mode=QComboBox();self.directory_mode.addItems(['中文分类视图','真实目录视图']);self.directory_mode.setCurrentIndex(self.store.setting('directory:viewmode',0));nav_layout.addWidget(self.directory_mode)
        self.tree=QTreeWidget(); self.tree.setHeaderLabel('文件导航');nav_layout.addWidget(self.tree); splitter.addWidget(nav_panel)
        self.tree.setMinimumHeight(45)
        self.model=FilesModel(); self.proxy=QIdentityProxyModel(); self.proxy.setSourceModel(self.model)
        self.table=QTableView(); self.table.setModel(self.proxy); self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows); self.table.setSelectionMode(QTableView.SelectionMode.ExtendedSelection); self.table.setSortingEnabled(True); self.table.setAlternatingRowColors(True); self.table.verticalHeader().hide(); self.table.setColumnWidth(0,255); self.table.setColumnWidth(1,70); self.table.setColumnWidth(2,82); self.table.setColumnWidth(3,145); splitter.addWidget(self.table)
        detail=QWidget(); form=QVBoxLayout(detail); self.info=QLabel('选择文件查看详情'); self.info.setWordWrap(True); self.info.setTextFormat(Qt.TextFormat.PlainText); self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); form.addWidget(self.info)
        self.preview=QLabel('图片预览'); self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter); self.preview.setMinimumHeight(130); form.addWidget(self.preview);self.preview.hide()
        self.preview_controller=PreviewController(self);self.preview_controller.ready.connect(self.preview_ready);self.preview_image=None
        self.path=QTextEdit(); self.path.setReadOnly(True); self.path.setFixedHeight(65); form.addWidget(self.path)
        form.addWidget(QLabel('备注')); self.note=QTextEdit(); self.note.setFixedHeight(82); form.addWidget(self.note)
        form.addWidget(QLabel('标签（逗号分隔）')); self.tags=QLineEdit(); form.addWidget(self.tags)
        self.favorite=QCheckBox('收藏此文件'); form.addWidget(self.favorite)
        self.edit_status=QLabel('未修改'); form.addWidget(self.edit_status)
        self.note.textChanged.connect(self.edit_changed)
        self.tags.textChanged.connect(self.edit_changed)
        self.favorite.toggled.connect(self.edit_changed)
        actions=QHBoxLayout(); form.addLayout(actions); self.button(actions,'保存备注',self.save_note); self.button(actions,'打开文件',self.open_file)
        self.button(form,'打开所在文件夹',self.reveal); self.button(form,'复制路径',lambda:QApplication.clipboard().setText(self.path.toPlainText()));self.button(form,'在真实目录视图定位',self.jump_to_directory); form.addStretch()
        self.detail_stack=QStackedWidget();self.detail_stack.addWidget(detail)
        directory_pane=QWidget();directory_form=QVBoxLayout(directory_pane);self.dir_text=QTextEdit();self.dir_text.setReadOnly(True);directory_form.addWidget(self.dir_text)
        self.button(directory_form,'打开实际目录',self.open_actual_directory);self.button(directory_form,'复制目录路径',lambda:QApplication.clipboard().setText(self.active_directory['path'] if self.active_directory else ''))
        self.button(directory_form,'修改当前目录名称 / 备注',self.edit_active_directory);self.detail_stack.addWidget(directory_pane);self.active_directory=None
        self.detail_scroll=QScrollArea();self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setMinimumHeight(55)
        self.detail_scroll.setWidget(self.detail_stack);splitter.addWidget(self.detail_scroll)
        self.table.setMinimumHeight(55)
        splitter.setChildrenCollapsible(False);splitter.setSizes([200,620,280])
        self.selection_bar=QWidget();browser_layout.addWidget(self.selection_bar)
        selection_layout=QHBoxLayout(self.selection_bar)
        selection_layout.setContentsMargins(0,0,0,0)
        self.selection_count=QLabel();selection_layout.addWidget(self.selection_count,1)
        self.clear_checks_button=self.button(selection_layout,'清空勾选',self.model.clear_checks)
        self.recycle_checked_button=self.button(selection_layout,'预览删除',self.preview_checked_files)
        self.recycle_checked_button.setProperty('kind','danger')
        self.model.checksChanged.connect(self.update_file_selection)
        self.selection_bar.hide()
        self.tree.itemSelectionChanged.connect(self.nav_changed); self.tree.itemDoubleClicked.connect(self.alias_dialog)
        self.table.selectionModel().selectionChanged.connect(self.selection_changed); self.table.doubleClicked.connect(lambda _:self.open_file())
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu); self.table.customContextMenuRequested.connect(self.context_menu)
        self.timer=QTimer(); self.timer.setSingleShot(True); self.timer.setInterval(220); self.timer.timeout.connect(self.reload)
        for w in [self.query,self.start,self.end,self.tag_filter]: w.textChanged.connect(lambda:self.timer.start())
        for w in [self.minimum,self.maximum]: w.valueChanged.connect(lambda:self.timer.start())
        self.category.currentIndexChanged.connect(self.reload); self.account.currentIndexChanged.connect(self.rebuild_tree)
        self.model.sortRequested.connect(self.sort_changed)
        self.tree.itemExpanded.connect(self.expand_directory)
        self.directory_mode.currentIndexChanged.connect(self.change_directory_view)
        self.delete_service=DeleteService(self.store)
        self.monitor=None;self.duplicate_dialog=None;self.statistics_dialog=None;self.task_kind=''
        self.duplicate_revision=0
        self.monitor_signals=MonitorSignals(self);self.monitor_signals.updated.connect(self.monitor_updated);self.monitor_signals.status.connect(self.monitor_status)
        self.monitor_label=QLabel('空闲 · 自动监控未开启');self.monitor_label.setMaximumWidth(480);self.monitor_label.setTextFormat(Qt.TextFormat.PlainText);self.statusBar().addPermanentWidget(self.monitor_label)
        self.page='directory';self.update_accounts(); self.rebuild_tree();self.switch_page('directory')
        if auto: QTimer.singleShot(500,self.startup)

    def button(self,layout,text,fn):
        b=QPushButton(text); b.clicked.connect(fn); layout.addWidget(b); return b

    def edit_file_selection(self,enabled):
        self.model.set_checkable(enabled)
        self.edit_selection_button.setText('完成选择' if enabled else '编辑选择')
        self.selection_bar.setVisible(enabled)

    def update_file_selection(self):
        count=len(self.model.checked_paths)
        self.selection_count.setText(f'已勾选 {count:,} 个文件')
        self.clear_checks_button.setEnabled(count>0)
        self.recycle_checked_button.setEnabled(count>0 and not (self.worker and self.worker.isRunning()))

    def preview_checked_files(self):
        self.delete_paths([row['path'] for row in self.model.checked_rows()])

    def switch_page(self,page):
        old=self.page
        if old!=page and not self.confirm_pending():
            for key,button in self.nav_buttons.items():button.setChecked(key==old)
            return False
        if old!=page and self.edit_selection_button.isChecked():
            self.edit_selection_button.setChecked(False)
            self.edit_file_selection(False)
        self.page=page
        for key,button in self.nav_buttons.items():button.setChecked(key==page)
        self.account.setVisible(page!='duplicates')
        self.page_title.setText(self.nav_buttons[page].text())
        if page=='duplicates':
            self.ensure_duplicates()
            self.pages.setCurrentWidget(self.duplicate_dialog)
        else:
            self.pages.setCurrentIndex(0)
        self.directory_panel.setVisible(page=='directory')
        self.add_button.setVisible(page=='directory')
        self.category.setVisible(page=='search')
        self.advanced_button.setVisible(page=='search')
        self.filters.setVisible(page=='search' and self.advanced_button.isChecked())
        self.detail_scroll.setVisible(self.details_button.isChecked())
        if old!=page and page!='duplicates':
            self.reload()
        return True

    def show_details(self):
        self.details_button.setChecked(True)
        self.detail_scroll.show()

    def open_collection(self,name):
        if not self.switch_page('directory'):return
        iterator=self.tree.invisibleRootItem()
        for index in range(iterator.childCount()):
            item=iterator.child(index)
            if (item.data(0,Qt.ItemDataRole.UserRole) or {}).get(name):
                self.tree.setCurrentItem(item)
                self.nav_changed()
                break

    def startup(self):
        if not self.store.accounts():
            for root in candidates():
                try: self.store.add(root)
                except ValueError: pass
            self.update_accounts()
        if self.store.accounts():
            if self.store.setting('monitor:enabled',False):self.start_monitor()
            else:self.scan()
        else:self.progress_label.setText('首次使用：点击“添加微信目录”选择微信文件夹；索引和备注保存在本地，微信原文件保持原样。')

    def update_accounts(self):
        selected=self.account.currentData(); self.account.blockSignals(True); self.account.clear(); self.account.addItem('全部账号','')
        for a in self.store.accounts(): self.account.addItem(a['name'],a['path'])
        idx=self.account.findData(selected); self.account.setCurrentIndex(max(idx,0)); self.account.blockSignals(False)

    def add_root(self):
        root=QFileDialog.getExistingDirectory(self,'选择微信根目录或账号目录')
        if not root:return
        if Path(self.store.path).resolve().is_relative_to(Path(root).resolve()):
            QMessageBox.warning(self,'目录不合适','程序数据目录位于所选目录内，请选择具体的微信目录。'); return
        try: self.store.add(root); self.update_accounts(); self.scan()
        except Exception as e: QMessageBox.warning(self,'无法添加',str(e))

    def rebuild_tree(self):
        if not self.confirm_pending():return
        self.tree.blockSignals(True); self.tree.clear()
        def item(parent,title,data):
            i=QTreeWidgetItem(parent,[title]); i.setData(0,Qt.ItemDataRole.UserRole,data); return i
        counts=self.store.category_counts(self.account.currentData() or '')
        all_item=item(self.tree,f'全部文件 ({sum(c["count"] for c in counts.values()):,})',{})
        item(self.tree,'最近文件（7 天）',{'recent':True})
        smart=item(self.tree,'智能管理',{})
        item(smart,'相近名称',{'duplicates':True});item(smart,'大文件',{'large':True});item(smart,'存储统计',{'statistics':True});smart.setExpanded(True)
        for cat in [*CATEGORIES,'其他文件']: item(self.tree,f'{cat} ({counts.get(cat,{}).get("count",0):,})',{'category':cat})
        item(self.tree,'★ 收藏',{'favorite':True})
        tag_root=item(self.tree,'我的标签（双击管理）',{'tags_view':True})
        for tag,count in sorted(self.store.tags().items()):item(tag_root,f'{tag} ({count:,})',{'tag':tag,'exact_tag':True})
        item(self.tree,'已不存在的文件',{'missing':True})
        chinese=self.directory_mode.currentIndex()==0
        raw=item(self.tree,'微信账号（中文分类）' if chinese else '微信原始目录（双击可备注）',{'raw':True});self.raw_directory_root=raw; self.directory_data={}
        selected=self.account.currentData()
        for a in self.store.accounts():
            if selected and selected!=a['path']:continue
            label=a['name'] if chinese else Path(a['path']).name+('（'+a['name']+'）' if a['name']!=Path(a['path']).name else '')
            root_item=item(raw,label,{'directory':a['path'],'account_edit':True,'account':a['path'],'loaded':chinese})
            root_item.setToolTip(0,a['path'])
            info=self.store.directory_info(a['path'])
            if info:self.directory_data[a['path']]=info
            if chinese:
                for label,paths in virtual_sections(a['path']):
                    paths=[canonical(p) for p in paths]
                    section=item(root_item,label,{'directories':paths,'account':a['path'],'virtual_label':label})
                    if not paths and label.startswith('其他'):
                        section.setData(0,Qt.ItemDataRole.UserRole,{'directory':a['path'],'account':a['path'],'virtual_other':True});QTreeWidgetItem(section,['展开查看原始目录…'])
                    for path in paths:
                        data=self.store.directory_info(path);alias=data['alias'] if data else ''
                        mapped=describe_directory(path,a['path'],alias)
                        child=item(section,mapped['name'],{'directory':path,'account':a['path'],'label':mapped['name']});child.setToolTip(0,path);child.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
            else:QTreeWidgetItem(root_item,['展开以加载目录…'])
        for index in range(self.tree.topLevelItemCount()):
            node=self.tree.topLevelItem(index)
            node.setHidden(node not in (all_item,raw))
        raw.setExpanded(True); self.tree.setCurrentItem(all_item); self.nav={}; self.tree.blockSignals(False); self.reload()

    def change_directory_view(self,index):
        previous=self.store.setting('directory:viewmode',0)
        if not self.confirm_pending():
            self.directory_mode.blockSignals(True);self.directory_mode.setCurrentIndex(previous);self.directory_mode.blockSignals(False);return
        self.store.set_setting('directory:viewmode',index);self.rebuild_tree()

    def show_directory_details(self,path,account):
        d=self.store.directory_details(path,account);self.active_directory=d;self.detail_stack.setCurrentIndex(1)
        scanned=datetime.fromtimestamp(d['scanned_at']).strftime('%Y-%m-%d %H:%M:%S') if d['scanned_at'] else '尚无成功扫描'
        quantity='未扫描' if d['count'] is None else f'{d["count"]:,} 个文件 / {human(d["size"])}'
        self.dir_text.setPlainText(f'中文显示名称：{d["name"]}\n原始名称：{d["original"]}\n识别状态：'+('已识别（按账号相对路径规则）' if d['known'] else '用途尚未确认')+f'\n\n{d["description"]}\n\n真实路径：\n{d["path"]}\n\n{quantity}\n最近成功扫描：{scanned}\n当前扫描状态：'+('完整' if d['complete'] else '未完成 / 有异常，请刷新后核对')+'\n\n备注：\n'+d['note'])

    def open_actual_directory(self):
        if not self.active_directory:return
        path=self.active_directory['path']
        if not Path(path).is_dir():QMessageBox.warning(self,'目录不可用','目录已不存在或无法访问。');return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def edit_active_directory(self):
        d=self.active_directory
        if d is None:return
        name,ok=QInputDialog.getText(self,'显示名称','仅在本程序内使用',text=d['name'])
        if not ok:return
        note,ok=QInputDialog.getMultiLineText(self,'目录备注','不改变微信原始目录',d['note'])
        if not ok:return
        if canonical(d['path'])==d['account']:self.store.rename(d['account'],name.strip() or d['original'],note);self.update_accounts()
        else:self.store.set_directory_meta(d['path'],name.strip(),note)
        self.rebuild_tree();self.nav={'directory':d['path'],'account':d['account']};self.reload()

    def jump_to_directory(self):
        if not self.active or not self.confirm_pending():return
        target=Path(self.active['path']).parent;account=self.active['account']
        if not self.switch_page('directory'):return
        self.directory_mode.setCurrentIndex(1)
        root=next((self.raw_directory_root.child(i) for i in range(self.raw_directory_root.childCount()) if (self.raw_directory_root.child(i).data(0,Qt.ItemDataRole.UserRole) or {}).get('directory')==account),None)
        if root is None:return
        current=root;path=Path(account)
        for part in target.relative_to(path).parts:
            self.expand_directory(current);current.setExpanded(True);path/=part;key=canonical(path)
            child=next((current.child(i) for i in range(current.childCount()) if (current.child(i).data(0,Qt.ItemDataRole.UserRole) or {}).get('directory')==key),None)
            if child is None:
                info=self.store.directory_info(key)
                if info is None:return
                child=QTreeWidgetItem(current,[Path(key).name]);child.setData(0,Qt.ItemDataRole.UserRole,{'directory':key,'account':account});child.setToolTip(0,key);child.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
            current=child
        self.tree.setCurrentItem(current);self.tree.scrollToItem(current);self.show_details()

    def nav_changed(self):
        items=self.tree.selectedItems(); self.nav=items[0].data(0,Qt.ItemDataRole.UserRole) if items else {}
        self.nav=self.nav or {}
        if self.nav.get('duplicates'):self.show_duplicates();return
        if self.nav.get('statistics'):self.statistics();return
        if self.nav.get('large'):self.sort_order='size';self.sort_desc=True
        self.reload()

    def sort_changed(self,column,order):
        if not self.confirm_pending():return
        self.sort_order=['name','category','size','mtime','account_name','tags','favorite'][column]
        self.sort_desc=order==Qt.SortOrder.DescendingOrder
        self.reload()

    def expand_directory(self,item):
        data=item.data(0,Qt.ItemDataRole.UserRole) or {}
        if not data.get('directory') or data.get('loaded'):return
        self.load_directory_page(item,data['directory'],0)

    def load_directory_page(self,item,path,offset):
        if offset==0:
            item.takeChildren()
            data=item.data(0,Qt.ItemDataRole.UserRole);data['loaded']=True;item.setData(0,Qt.ItemDataRole.UserRole,data)
        children=self.store.directory_children(path,offset=offset)
        for d in children:
            self.directory_data[d['path']]=d;p=Path(d['path'])
            label=describe_directory(d['path'],d['account'],d['alias'])['name'] if self.directory_mode.currentIndex()==0 else p.name+('（'+d['alias']+'）' if d['alias'] else '')
            node=QTreeWidgetItem(item,[f'{label} ({d["count"]:,})'])
            node.setData(0,Qt.ItemDataRole.UserRole,{'directory':d['path'],'account':d['account'],'label':d['alias'] or p.name})
            node.setToolTip(0,f'{d["path"]}\n{d["count"]:,} 个文件 / {human(d["size"])}')
            node.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
        if len(children)==200:
            more=QTreeWidgetItem(item,['加载更多目录…'])
            more.setData(0,Qt.ItemDataRole.UserRole,{'more_parent':path,'offset':offset+200})

    def alias_dialog(self,item,column):
        data=item.data(0,Qt.ItemDataRole.UserRole) or {}; path=data.get('directory')
        if data.get('tags_view'):self.tag_center();return
        if data.get('more_parent'):
            parent=item.parent();offset=data['offset'];parent.takeChild(parent.indexOfChild(item));self.load_directory_page(parent,data['more_parent'],offset);return
        if not path:return
        name,ok=QInputDialog.getText(self,'自定义显示名称','只在本程序内生效：',text=data.get('label',item.text(0)))
        if not ok or not name.strip():return
        if data.get('account_edit'):
            a=next(a for a in self.store.accounts() if a['path']==path)
            note,ok=QInputDialog.getMultiLineText(self,'账号备注','备注',a['note'])
            if not ok:return
            self.store.rename(path,name.strip(),note); self.update_accounts()
        else:
            old=self.store.directory_info(path)
            note,ok=QInputDialog.getMultiLineText(self,'目录备注','只保存在本程序中',old.get('note','') if old else '')
            if not ok:return
            self.store.set_directory_meta(path,name.strip(),note)
        self.rebuild_tree()

    def reload(self,*args,preserve=False):
        if not self.confirm_pending(): return
        selected_paths=[r['path'] for r in self.selected()] if preserve else []
        scroll=self.table.verticalScrollBar().value() if preserve else 0
        searching=self.page=='search'
        nav={} if searching else self.nav
        for w in ([self.start,self.end] if searching else []):
            text=w.text().strip()
            if text:
                try: datetime.strptime(text,'%Y-%m-%d')
                except ValueError:self.statusBar().showMessage('日期格式应为 YYYY-MM-DD'); return
        if searching and self.start.text() and self.end.text() and self.start.text()>self.end.text():
            self.statusBar().showMessage('起始日期不能晚于结束日期。');return
        if searching and self.maximum.value() and self.maximum.value()<self.minimum.value():
            self.statusBar().showMessage('大小上限不能小于下限。');return
        filters=dict(
            query=self.query.text().strip() if searching else '',
            category=nav.get('category') or (self.category.currentText() if searching and self.category.currentIndex()>0 else ''),
            account=nav.get('account') or self.account.currentData() or '',
            favorite=nav.get('favorite',False),
            tag=nav.get('tag') or (self.tag_filter.text().strip() if searching else ''),
            exact_tag=nav.get('exact_tag',False),
            minimum=int(self.minimum.value()*1024**2) if searching else 0,
            maximum=int(self.maximum.value()*1024**2) if searching and self.maximum.value() else None,
            start=self.start.text().strip() if searching else '',
            end=self.end.text().strip() if searching else '',
            directory=nav.get('directory',''),missing=nav.get('missing',False))
        if 'directories' in nav:filters['directories']=nav['directories']
        if nav.get('recent'):
            from datetime import timedelta
            filters['start']=(datetime.now()-timedelta(days=7)).strftime('%Y-%m-%d')
        page=self.store.search_page(order=self.sort_order,descending=self.sort_desc,**filters)
        rows=page.rows
        self.preview_controller.clear();self.preview_image=None
        self.preview.hide()
        self.active=None; self.model.configure(self.store,filters,self.sort_order,self.sort_desc,page); self.info.setText('选择文件查看详情'); self.path.clear(); self.note.clear(); self.tags.clear(); self.preview.clear(); self.favorite.setChecked(False)
        if self.model.checkable:self.model.clear_checks()
        d=self.directory_data.get(nav.get('directory'))
        text=f'共 {page.total:,} 个可管理文件 · {human(page.size)} · 首批 {len(rows)} 个，向下滚动加载更多'
        if d:text+=f' | 原目录含内部数据：{d["count"]:,} 个文件 / {human(d["size"])}'
        self.statusBar().showMessage(text)
        self.empty_label.setVisible(not rows)
        if not rows:
            self.empty_label.setText('没有匹配的文件，请调整搜索或筛选条件。' if searching else '此处暂无可管理的文件。请添加微信目录或刷新索引。')
        self.active_directory=None;self.detail_stack.setCurrentIndex(0)
        if nav.get('directory'):
            directory=self.store.directory_info(nav['directory']);account=nav.get('account') or (directory['account'] if directory else None)
            if account:self.show_directory_details(nav['directory'],account)
        elif nav.get('virtual_label'):
            self.dir_text.setPlainText(nav['virtual_label']+'\n已发现路径：\n'+('\n'.join(nav.get('directories',[])) or '当前未发现 / 尚未扫描。'));self.detail_stack.setCurrentIndex(1)
        if selected_paths:
            index=next((i for i,r in enumerate(self.model.rows) if r['path'] in selected_paths),None)
            if index is not None:self.table.selectRow(index)
        if preserve:self.table.verticalScrollBar().setValue(scroll)

    def selected(self):
        return [self.model.rows[self.proxy.mapToSource(i).row()] for i in self.table.selectionModel().selectedRows()]

    def selection_changed(self,*args):
        if not self.confirm_pending():
            if self.active:
                index=next((i for i,r in enumerate(self.model.rows) if r['path']==self.active['path']),None)
                if index is not None:
                    self.table.selectionModel().blockSignals(True)
                    self.table.selectRow(self.proxy.mapFromSource(self.model.index(index,0)).row())
                    self.table.selectionModel().blockSignals(False)
            return
        selected=self.selected()
        if len(selected)==1:
            row=selected[0]
            self.statusBar().showMessage(f'{row["name"]} · {human(row["size"])} · {row["account_name"]}')
        else:
            self.statusBar().showMessage(f'选中 {len(selected)} 个 · {human(sum(r["size"] for r in selected))}')
        if not selected:return
        r=selected[0]; self.active=r;self.active_directory=None;self.detail_stack.setCurrentIndex(0); self.info.setText(f'{r["name"]}\n{r["category"]} · {human(r["size"])}\n账号：{r["account_name"]}'+('\n文件已不存在' if r['missing'] else '')); self.path.setPlainText(r['path']); self.note.setPlainText(r['note']); self.tags.setText(r['tags']); self.favorite.setChecked(bool(r['favorite'])); self.preview.clear()
        self.preview_controller.clear();self.preview_image=None
        self.preview.setVisible(r['category']=='图片' and not r['missing'])
        if r['category']=='图片' and not r['missing']:
            self.preview.setText('正在生成预览…');self.preview_controller.request(r['path'],r['size'])
        else:self.preview.setText('使用系统关联程序打开；加密附件仅显示元数据')
        self.edit_changed()

    def preview_ready(self,img,message):
        self.preview_image=img
        if message:self.preview.setText(message)
        elif img is not None:self.preview.setPixmap(QPixmap.fromImage(img).scaled(max(self.preview.width()-8,1),max(self.preview.height()-8,1),Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if getattr(self,'preview_image',None) is not None:self.preview_ready(self.preview_image,'')

    def save_note(self):
        if not self.active: return False
        try:
            self.store.annotate(self.active['path'],self.note.toPlainText(),self.tags.text(),self.favorite.isChecked())
            self.active.update(note=self.note.toPlainText(),tags=self.tags.text(),favorite=int(self.favorite.isChecked()))
            index=next(i for i,r in enumerate(self.model.rows) if r['path']==self.active['path'])
            self.model.dataChanged.emit(self.model.index(index,0),self.model.index(index,6))
            self.refresh_tag_nodes()
            self.edit_status.setText('✓ 已保存'); self.statusBar().showMessage('备注、标签和收藏已保存',5000)
            return True
        except Exception as e:
            QMessageBox.warning(self,'保存失败',str(e)); return False

    def refresh_tag_nodes(self):
        for i in range(self.tree.topLevelItemCount()):
            root=self.tree.topLevelItem(i);data=root.data(0,Qt.ItemDataRole.UserRole) or {}
            if not data.get('tags_view'):continue
            self.tree.blockSignals(True)
            root.takeChildren()
            for tag,count in sorted(self.store.tags().items())[:200]:
                node=QTreeWidgetItem(root,[f'{tag} ({count:,})'])
                node.setData(0,Qt.ItemDataRole.UserRole,{'tag':tag,'exact_tag':True})
            self.tree.blockSignals(False)
            break

    def is_dirty(self):
        return bool(self.active and (self.note.toPlainText()!=self.active['note'] or self.tags.text()!=self.active['tags'] or self.favorite.isChecked()!=bool(self.active['favorite'])))

    def edit_changed(self,*args):
        self.edit_status.setText('● 有未保存的修改' if self.is_dirty() else '未修改')

    def confirm_pending(self):
        if not self.is_dirty(): return True
        choice=QMessageBox.warning(self,'尚未保存','备注、标签或收藏有修改，是否保存？',QMessageBox.StandardButton.Save|QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Save)
        if choice==QMessageBox.StandardButton.Save: return self.save_note()
        if choice==QMessageBox.StandardButton.Discard:
            # Keep the indexed values unchanged; the caller can now change context.
            self.note.blockSignals(True); self.tags.blockSignals(True); self.favorite.blockSignals(True)
            self.note.setPlainText(self.active['note']);self.tags.setText(self.active['tags']);self.favorite.setChecked(bool(self.active['favorite']))
            self.note.blockSignals(False);self.tags.blockSignals(False);self.favorite.blockSignals(False)
            self.edit_changed(); return True
        return False

    def open_file(self):
        if not self.active:return
        p=Path(self.active['path'])
        if not p.is_file():QMessageBox.warning(self,'文件不可用','文件已不存在或无法访问，请刷新索引。'); return
        if p.suffix.lower() in {'.exe','.bat','.cmd','.ps1','.vbs','.js','.msi','.scr','.com','.lnk'}:
            if QMessageBox.question(self,'运行程序','此文件是可执行文件或脚本。是否调用系统打开？')!=QMessageBox.StandardButton.Yes:return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(p))):QMessageBox.warning(self,'打开失败','系统未能打开此文件，请检查文件关联。')

    def reveal(self):
        if self.active:
            if sys.platform=='win32' and Path(self.active['path']).is_file():
                import subprocess
                subprocess.Popen(['explorer.exe','/select,',os.path.normpath(self.active['path'])])
            else:QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.active['path']).parent)))

    def context_menu(self,pos):
        index=self.table.indexAt(pos)
        if index.isValid() and not self.table.selectionModel().isSelected(index):
            self.table.selectRow(index.row())
        m=QMenu(self); m.addAction('打开文件',self.open_file); m.addAction('打开所在文件夹',self.reveal);m.addAction('在真实目录视图定位',self.jump_to_directory); m.addAction('复制路径',lambda:QApplication.clipboard().setText(self.path.toPlainText()));m.addAction('查看详情',self.show_details); m.addAction('复制 / 导出所选',self.export); m.addAction('批量添加标签',self.batch_tags);m.addAction('批量管理所选',lambda:self.bulk_dialog(False));m.addAction('批量管理当前筛选结果',lambda:self.bulk_dialog(True));m.addSeparator();m.addAction('移入回收站（仅所选文件）',lambda:self.delete_paths([r['path'] for r in self.selected()])).setEnabled(bool(self.selected())); m.exec(self.table.viewport().mapToGlobal(pos))

    def start_worker(self,fn,done,scan=False):
        if self.worker and self.worker.isRunning():QMessageBox.information(self,'任务运行中','请等待当前任务完成。'); return
        self.scan_button.setEnabled(False); self.add_button.setEnabled(False); self.stop_button.setEnabled(scan)
        self.stop_button.setVisible(scan)
        self.progress_bar.show()
        self.worker=Worker(fn); self.worker.progress.connect(self.update_progress)
        self.worker.done.connect(done); self.worker.finished.connect(self.task_finished); self.worker.start()
        self.update_file_selection()

    def update_progress(self,text):
        self.progress_label.setText(text);self.statusBar().showMessage(text)

    def task_finished(self):self.scan_button.setEnabled(True); self.add_button.setEnabled(True); self.stop_button.hide();self.progress_bar.hide();self.update_file_selection()

    def scan(self):
        if not self.confirm_pending(): return
        self.task_kind='scan'
        self.statusBar().showMessage('开始扫描…')
        self.start_worker(lambda progress:self.store.scan(progress,lambda:QThread.currentThread().isInterruptionRequested()),self.scan_done,True)

    def scan_done(self,out):
        self.rebuild_tree()
        if 'error' in out:
            self.invalidate_duplicates()
            self.store.set_setting('state:scan',{'complete':False,'running':False,'errors':[out['error']]});QMessageBox.warning(self,'扫描失败',out['error']); return
        r=out['result']; self.statusBar().showMessage(f'扫描'+('已停止' if r['cancelled'] else '完成')+f'：{r["files"]:,} 个可管理文件；{len(r["errors"])} 个访问异常')
        self.refresh_duplicate_validity(r)
        self.progress_label.setText(f'扫描'+('已取消' if r['cancelled'] else '完成')+f'；{r["files"]:,} 个可管理文件；{len(r["errors"])} 个访问异常')
        if r['errors']:QMessageBox.warning(self,'部分目录无法读取','已保留未能完整扫描账号的旧文件状态。\n'+'\n'.join(r['errors'][:15]))
        if self.store.setting('monitor:enabled',False):
            expected={a['path'] for a in self.store.accounts()}
            if not self.monitor or set(getattr(self.monitor,'roots',[]))!=expected:self.restart_monitor()

    def statistics(self):
        if self.statistics_dialog is None:self.statistics_dialog=StatisticsDialog(self.store,self)
        else:self.statistics_dialog.refresh()
        self.statistics_dialog.show();self.statistics_dialog.raise_()

    def tag_center(self):
        if not self.confirm_pending():return
        selected=[];dialog=TagDialog(self.store,self);dialog.tagSelected.connect(selected.append);dialog.exec()
        self.rebuild_tree()
        if selected and self.switch_page('directory'):
            self.nav={'tag':selected[0],'exact_tag':True};self.reload()

    def show_history(self):
        DeleteHistoryDialog(self.delete_service,self).exec()

    def toggle_monitor(self):
        enabled=not self.store.setting('monitor:enabled',False)
        self.store.set_setting('monitor:enabled',enabled)
        if enabled:self.start_monitor()
        elif self.monitor:self.monitor.stop()

    def open_recycle_bin(self):
        import subprocess
        if sys.platform=='win32':subprocess.Popen(['explorer.exe','shell:RecycleBinFolder'])
        else:QMessageBox.information(self,'不支持','仅支持 Windows 回收站。')

    def batch_tags(self):
        if not self.confirm_pending():return
        rows=self.selected()
        if not rows:QMessageBox.information(self,'添加标签','请先选择一个或多个文件。');return
        tags,ok=QInputDialog.getText(self,'批量添加标签',f'为 {len(rows)} 个文件添加标签（逗号分隔）')
        if ok:
            try:self.store.add_tags([r['path'] for r in rows],tags);self.reload();self.statusBar().showMessage('批量标签已保存',5000)
            except ValueError as e:QMessageBox.warning(self,'标签无效',str(e))

    def settings(self):
        if not self.confirm_pending():return
        action,ok=QInputDialog.getItem(self,'设置与数据','选择操作',['备份索引、备注和收藏','恢复备份','开启/关闭自动监控','重新启动自动监控','删除记录（仅本机）','打开 Windows 回收站','查看本地数据位置','关于与许可证'],0,False)
        if not ok:return
        if action.startswith('备份'):
            target,_=QFileDialog.getSaveFileName(self,'备份数据','微信文件管理器备份.sqlite','SQLite (*.sqlite)')
            if not target:return
            if canonical(target)==canonical(self.store.path) or any(Path(target).resolve().is_relative_to(Path(root).resolve()) for root in self.store.source_roots()):QMessageBox.warning(self,'无法备份','请选择微信原目录和当前数据库以外的位置。'); return
            try:self.store.backup(target); QMessageBox.information(self,'备份完成',target)
            except Exception as e:QMessageBox.warning(self,'备份失败',str(e))
        elif action=='恢复备份': self.restore_backup()
        elif action=='开启/关闭自动监控':self.toggle_monitor()
        elif action=='重新启动自动监控':self.store.set_setting('monitor:enabled',True);self.restart_monitor()
        elif action=='删除记录（仅本机）':self.show_history()
        elif action=='打开 Windows 回收站':self.open_recycle_bin()
        elif action.startswith('查看'):QMessageBox.information(self,'本地数据',str(self.store.path))
        else:QMessageBox.information(self,'关于','微信文件管理器 '+__version__+'\n目录识别和月份分类参考 oracis/wechat-file-organizer-gui (MIT)。\n本软件独立于微信，不解密聊天记录。\n开源许可见程序目录 licenses 文件夹。')

    def export(self):
        self.export_rows(self.selected())

    def export_rows(self,rows):
        if not rows:QMessageBox.information(self,'选择文件','请先在列表中选择需要复制的文件。'); return
        target=QFileDialog.getExistingDirectory(self,'选择归档副本的保存目录')
        if not target:return
        mode,ok=QInputDialog.getItem(self,'归档方式','目录组织',['类型+月份','类型','月份','平铺'],0,False)
        if not ok:return
        conflict,ok=QInputDialog.getItem(self,'重名处理','目标存在同名文件时',['自动更名','跳过'],0,False)
        if not ok:return
        if QMessageBox.question(self,'确认复制',f'复制 {len(rows)} 个文件\n源目录：微信账号内的原始路径（详情栏可查看）\n目标：{target}\n方式：{mode}；重名：{conflict}\n仅创建副本，源文件保持原样。')!=QMessageBox.StandardButton.Yes:return
        self.start_worker(lambda progress:export_files(rows,target,mode,conflict,self.store.source_roots(),progress),self.export_done)

    def restore_backup(self):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self,'任务运行中','请等待扫描或导出完成再恢复。');return
        if not self.confirm_pending():return
        source,_=QFileDialog.getOpenFileName(self,'选择本程序备份','','SQLite (*.sqlite *.sqlite3 *.db)')
        if not source:return
        if any(Path(source).resolve().is_relative_to(Path(root).resolve()) for root in self.store.source_roots()):
            QMessageBox.warning(self,'无法恢复','请使用微信原始目录以外的程序备份。');return
        if QMessageBox.question(self,'恢复备份','恢复将替换当前索引和个人设置。恢复前会自动备份当前数据，是否继续？')!=QMessageBox.StandardButton.Yes:return
        try:
            if self.monitor and not self.monitor.stop():raise RuntimeError('监控仍在停止，请稍后再恢复')
            rollback=self.store.restore(source);self.invalidate_duplicates();self.active=None;self.update_accounts();self.rebuild_tree()
            QMessageBox.information(self,'恢复完成','恢复成功。原数据自动备份至：\n'+str(rollback))
        except Exception as e:QMessageBox.warning(self,'恢复失败',str(e))
        finally:
            if self.store.setting('monitor:enabled',False):self.start_monitor()

    def export_done(self,out):
        if 'error' in out:QMessageBox.warning(self,'导出失败',out['error']); return
        r=out['result']; QMessageBox.information(self,'复制结果',f'成功 {r["copied"]}；跳过 {r["skipped"]}；失败 {len(r["failures"])}\n清单：{r["manifest"]}\n'+'\n'.join(r['failures'][:10]))

    def show_duplicates(self):
        self.switch_page('duplicates')

    def ensure_duplicates(self):
        if self.duplicate_dialog is None:
            self.duplicate_dialog=NameMatchesPage(self.run_name_detection,self)
            self.duplicate_dialog.recycleRequested.connect(self.preview_name_matches)
            self.pages.addWidget(self.duplicate_dialog)

    def invalidate_duplicates(self):
        self.duplicate_revision+=1
        state=self.store.setting('state:duplicates',{})
        if state.get('complete'):
            self.store.set_setting('state:duplicates',dict(state,complete=False))
        if self.duplicate_dialog:
            self.duplicate_dialog.invalidate()

    def refresh_duplicate_validity(self,result):
        if result.get('changed') or result.get('deleted') or result.get('errors'):
            self.invalidate_duplicates()

    def run_name_detection(self):
        if self.worker and self.worker.isRunning():
            self.update_progress('当前有任务在运行，可先点「停止任务」。')
            return
        revision=self.duplicate_revision
        self.update_progress('正在查找名称相近的文件…')
        def detect(progress):
            cancelled=QThread.currentThread().isInterruptionRequested
            try:
                return name_groups(self.store,cancelled,progress)
            except HashCancelled:
                return None
        self.start_worker(detect,lambda out:self.name_detection_done(out,revision),True)

    def name_detection_done(self,out,revision):
        if revision!=self.duplicate_revision:
            self.update_progress('索引已变化，请重新查找相近名称。')
        elif 'error' in out:
            self.update_progress('名称查找失败：'+out['error'])
        elif out['result'] is None:
            self.update_progress('已停止名称查找。')
        else:
            groups,skipped=out['result']
            self.duplicate_dialog.set_results(groups,f'名称相近 {len(groups):,} 组 · 跳过 {skipped:,} 个文件。请核对内容后勾选。')
            self.update_progress('展开文件组，单击文件可在右侧预览。')

    def start_monitor(self):
        if self.monitor and self.monitor.thread and self.monitor.thread.is_alive():return
        self.monitor=FileMonitor(self.store,self.monitor_signals.updated.emit,self.monitor_signals.status.emit)
        self.monitor.start()

    def restart_monitor(self):
        if self.monitor and not self.monitor.stop():return
        self.monitor=None;self.start_monitor()

    def monitor_status(self,text):
        latest=self.store.setting('scan:last_success',None)
        stamp=datetime.fromtimestamp(latest).strftime('%H:%M:%S') if latest else '未完整扫描'
        self.monitor_label.setText(text+' · 全量扫描 '+stamp);self.monitor_label.setToolTip(text)

    def monitor_updated(self,message):
        self.refresh_duplicate_validity(message['result'])
        if message['result'].get('cancelled'):return
        if self.is_dirty():self.statusBar().showMessage('索引已自动更新；当前有未保存修改，保存或刷新后查看新列表。');return
        self.reload(preserve=True)
        counts=self.store.category_counts(self.account.currentData() or '')
        for i in range(self.tree.topLevelItemCount()):
            item=self.tree.topLevelItem(i);data=item.data(0,Qt.ItemDataRole.UserRole) or {}
            if data.get('category'):item.setText(0,f'{data["category"]} ({counts.get(data["category"],{}).get("count",0):,})')
            elif not data and item.text(0).startswith('全部文件'):item.setText(0,f'全部文件 ({sum(c["count"] for c in counts.values()):,})')
        if self.statistics_dialog and self.statistics_dialog.isVisible():self.statistics_dialog.refresh()

    def bulk_dialog(self,filtered=False):
        if not self.confirm_pending():return
        rows=self.selected();count=self.model.total if filtered else len(rows)
        if not count:QMessageBox.information(self,'批量管理','当前没有可操作的文件。');return
        operations=['添加标签','移除标签','收藏','取消收藏']
        label,ok=QInputDialog.getItem(self,'批量管理',f'范围：'+('全部筛选结果' if filtered else '所选文件')+f'，预计 {count:,} 个文件',operations,0,False)
        if not ok:return
        tags=''
        if label in operations[:2]:
            tags,ok=QInputDialog.getText(self,label,'标签名称（逗号分隔；仅修改程序索引）')
            if not ok:return
        if QMessageBox.question(self,'确认批量操作',f'{label}：预计 {count:,} 个文件。只修改本程序数据，是否继续？')!=QMessageBox.StandardButton.Yes:return
        op=['add_tags','remove_tags','favorite','unfavorite'][operations.index(label)]
        filters=dict(self.model.filters);paths=None if filtered else [r['path'] for r in rows]
        self.task_kind='bulk'
        self.start_worker(lambda progress:self.store.bulk_manage(op,tags,paths,filters,lambda:QThread.currentThread().isInterruptionRequested()),self.bulk_done,True)

    def bulk_done(self,out):
        if 'error' in out:QMessageBox.warning(self,'批量操作失败',out['error']);return
        r=out['result'];self.reload(preserve=True);self.refresh_tag_nodes()
        QMessageBox.information(self,'批量操作结果',f'成功 {r["success"]:,}；实际变更 {r["changed"]:,}；失败 {len(r["failures"])}'+('\n已取消，未提交变更' if r['cancelled'] else '')+'\n'+'\n'.join(r['failures'][:10]))

    def preview_name_matches(self,rows):
        snapshots={row['path']:indexed_signature(row) for row in rows}
        self.delete_paths(list(snapshots),expected_snapshots=snapshots)

    def delete_paths(self,paths,expected_snapshots=None):
        if not paths:QMessageBox.information(self,'选择文件','请主动选择需要处理的文件。');return
        if not self.confirm_pending():return
        if self.worker and self.worker.isRunning():QMessageBox.information(self,'任务运行中','请等待当前任务完成再准备删除。');return
        self.task_kind='delete_prepare'
        def prepare(progress):
            cancelled=QThread.currentThread().isInterruptionRequested
            return self.delete_service.prepare(paths,cancelled=cancelled,progress=progress,
                                               expected_snapshots=expected_snapshots)
        self.start_worker(prepare,self.delete_prepared,True)

    def delete_prepared(self,out):
        if self.worker and self.worker.isRunning():QTimer.singleShot(10,lambda:self.delete_prepared(out));return
        if 'error' in out:QMessageBox.warning(self,'未开始删除',out['error']);return
        plan=out['result'];dialog=DeleteDialog(plan,self)
        if dialog.exec()!=QDialog.DialogCode.Accepted:
            self.task_kind='delete_cancel'
            self.start_worker(lambda progress:self.delete_service.execute(plan,confirmed=False),
                              lambda result:self.update_progress(result.get('error','已取消，没有删除文件。')))
            return
        original_ack=dialog.original_ack.isChecked()
        excluded=dialog.excluded_paths()
        self.task_kind='delete'
        self.start_worker(lambda progress:self.delete_service.execute(plan,True,original_ack,lambda:QThread.currentThread().isInterruptionRequested(),progress,excluded),self.delete_done,True)

    def delete_done(self,out):
        if 'error' in out:QMessageBox.warning(self,'处理异常','请核对删除记录与回收站：\n'+out['error']);return
        r=out['result'];self.reload(preserve=True)
        self.refresh_deleted_counts([row['path'] for row in r['items'] if row['result'] in {'success','uncertain'}])
        if r['success'] or r['uncertain']:self.invalidate_duplicates()
        if self.statistics_dialog:self.statistics_dialog.refresh()
        report=QDialog(self);report.setWindowTitle('清理操作完成');report.resize(490,210);layout=QVBoxLayout(report)
        summary=QLabel(f'已移入回收站 {r["success"]} 个文件\n失败 {r["failed"]} · 跳过 {r["skipped"]} · 取消 {r["cancelled"]} · 待核对 {r["uncertain"]}\n回收站接收容量 {human(r["recycled_bytes"])}，实际释放空间以系统为准。')
        summary.setWordWrap(True);layout.addWidget(summary,1)
        actions=QHBoxLayout();layout.addLayout(actions)
        self.button(actions,'查看处理记录',self.show_history)
        self.button(actions,'打开回收站',self.open_recycle_bin)
        self.button(actions,'完成',report.accept)
        report.exec()

    def refresh_deleted_counts(self,paths):
        from PySide6.QtWidgets import QTreeWidgetItemIterator
        names={a['path']:a['name'] for a in self.store.accounts()};accounts=[Path(path) for path in names];parents=set()
        for path in paths:
            p=Path(path)
            root=next((root for root in accounts if p.is_relative_to(root)),None)
            if root is None:continue
            for parent in p.parents:
                if not parent.is_relative_to(root):break
                parents.add(canonical(parent))
        info={};ordered=list(parents)
        with self.store.connect() as db:
            for start in range(0,len(ordered),200):
                part=ordered[start:start+200]
                info.update({row['path']:dict(row) for row in db.execute('SELECT * FROM directories WHERE path IN ('+','.join('?' for _ in part)+')',part)})
        counts=self.store.category_counts(self.account.currentData() or '')
        iterator=QTreeWidgetItemIterator(self.tree)
        while iterator.value():
            item=iterator.value();data=item.data(0,Qt.ItemDataRole.UserRole) or {};path=data.get('directory')
            if path in info:
                d=info[path];self.directory_data[path]=d
                if data.get('virtual_other'):label='其他数据 / 全部原始目录'
                elif data.get('account_edit'):
                    name=names.get(path,Path(path).name)
                    label=name if self.directory_mode.currentIndex()==0 else Path(path).name+('（'+name+'）' if name!=Path(path).name else '')
                elif self.directory_mode.currentIndex()==0:label=describe_directory(path,d['account'],d['alias'])['name']
                else:label=Path(path).name+('（'+d['alias']+'）' if d['alias'] else '')
                item.setText(0,f'{label} ({d["count"]:,})')
            elif data.get('category'):item.setText(0,f'{data["category"]} ({counts.get(data["category"],{}).get("count",0):,})')
            elif not data and item.text(0).startswith('全部文件'):item.setText(0,f'全部文件 ({sum(c["count"] for c in counts.values()):,})')
            iterator+=1

    def closeEvent(self,event):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption(); QMessageBox.information(self,'任务仍在运行','已请求停止扫描。请等待当前扫描或复制完成后关闭。'); event.ignore()
        elif self.confirm_pending():
            if self.monitor and not self.monitor.stop():event.ignore();return
            if self.duplicate_dialog:self.duplicate_dialog.close()
            if self.statistics_dialog:self.statistics_dialog.close()
            event.accept()
        else:event.ignore()
