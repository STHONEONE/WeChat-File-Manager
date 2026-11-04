import json
import os
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QAbstractTableModel, QModelIndex, QSortFilterProxyModel, QIdentityProxyModel, QTimer, QUrl,QObject
from PySide6.QtGui import QDesktopServices, QImageReader, QPixmap, QIcon, QPainter, QColor, QFontDatabase, QFont
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QLineEdit,QComboBox,QPushButton,QSplitter,QTreeWidget,QTreeWidgetItem,QTableView,QLabel,QTextEdit,QCheckBox,QFormLayout,QFileDialog,QMessageBox,QInputDialog,QMenu,QDoubleSpinBox,QDialog,QDialogButtonBox,QProgressBar)
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
from app.ui.duplicates import DuplicatesDialog
from app.ui.statistics_view import StatisticsDialog
from app.file_monitor import FileMonitor

class MonitorSignals(QObject):
    updated=Signal(object)
    status=Signal(str)

class Window(QMainWindow):
    def __init__(self,store, auto=True):
        super().__init__(); self.store=store; self.worker=None; self.active=None; self.nav={}; self.directory_data={}; self.sort_order='mtime'; self.sort_desc=True
        font=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/'msyh.ttc'
        if font.exists(): QFontDatabase.addApplicationFont(str(font))
        self.setFont(QFont('Microsoft YaHei',10))
        self.setStyleSheet('QWidget {font-family:"Microsoft YaHei";font-size:13px;} QLabel#title {font-size:26px;font-weight:600;color:#143b32;} QLabel#caption {color:#687a74;margin-bottom:10px;} QPushButton {padding:7px 10px;border:1px solid #cbd8d2;border-radius:5px;background:white;} QLineEdit,QComboBox,QDoubleSpinBox,QTextEdit {padding:6px;border:1px solid #d3ded8;border-radius:4px;} QHeaderView::section {padding:8px;background:#eaf1ed;}')
        self.setWindowTitle('微信文件管理器 '+__version__+' 开发版'); self.resize(1440,900)
        outer=QWidget(); self.setCentralWidget(outer); layout=QVBoxLayout(outer); layout.setContentsMargins(18,16,18,12)
        title=QLabel('微信文件管理器'); title.setObjectName('title'); layout.addWidget(title)
        caption=QLabel('中文目录 · 跨账号搜索 · 本地收藏与归档'); caption.setObjectName('caption'); layout.addWidget(caption)
        toolbar=QHBoxLayout(); layout.addLayout(toolbar)
        self.query=QLineEdit(); self.query.setPlaceholderText('搜索文件名、扩展名、标签或备注…'); toolbar.addWidget(self.query,3)
        self.category=QComboBox(); self.category.addItems(['全部类型',*CATEGORIES,'其他文件']); toolbar.addWidget(self.category)
        self.account=QComboBox(); toolbar.addWidget(self.account,1)
        self.add_button=self.button(toolbar,'添加微信目录',self.add_root)
        self.scan_button=self.button(toolbar,'刷新索引',self.scan)
        self.stop_button=self.button(toolbar,'停止',lambda:self.worker.requestInterruption() if self.worker else None); self.stop_button.setEnabled(False)
        self.button(toolbar,'设置与备份',self.settings)
        filters=QHBoxLayout(); layout.addLayout(filters)
        self.start=DateFilter('起始日期')
        self.end=DateFilter('结束日期')
        self.minimum=QDoubleSpinBox(); self.minimum.setRange(0,1e9); self.minimum.setSuffix(' MiB 起');self.minimum.setMaximumWidth(150)
        self.maximum=QDoubleSpinBox(); self.maximum.setRange(0,1e9); self.maximum.setSuffix(' MiB 止');self.maximum.setMaximumWidth(150);self.maximum.setToolTip('大小上限；0 表示不限')
        self.tag_filter=QLineEdit(); self.tag_filter.setPlaceholderText('标签筛选');self.tag_filter.setMinimumWidth(120)
        for w in [self.start,self.end,self.minimum,self.maximum,self.tag_filter]: filters.addWidget(w)
        self.button(filters,'统计',self.statistics); self.button(filters,'复制 / 导出所选',self.export)
        self.button(toolbar,'标签管理',self.tag_center)
        self.progress_label=QLabel('就绪');self.progress_label.setWordWrap(True);layout.addWidget(self.progress_label)
        self.progress_bar=QProgressBar();self.progress_bar.setRange(0,0);self.progress_bar.hide();layout.addWidget(self.progress_bar)
        splitter=QSplitter(); layout.addWidget(splitter,1)
        self.tree=QTreeWidget(); self.tree.setHeaderLabel('文件导航'); splitter.addWidget(self.tree)
        self.model=FilesModel(); self.proxy=QIdentityProxyModel(); self.proxy.setSourceModel(self.model)
        self.table=QTableView(); self.table.setModel(self.proxy); self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows); self.table.setSelectionMode(QTableView.SelectionMode.ExtendedSelection); self.table.setSortingEnabled(True); self.table.setAlternatingRowColors(True); self.table.verticalHeader().hide(); self.table.setColumnWidth(0,360); self.table.setColumnWidth(3,155); splitter.addWidget(self.table)
        detail=QWidget(); form=QVBoxLayout(detail); self.info=QLabel('选择文件查看详情'); self.info.setWordWrap(True); self.info.setTextFormat(Qt.TextFormat.PlainText); self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); form.addWidget(self.info)
        self.preview=QLabel('图片预览'); self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter); self.preview.setMinimumHeight(180); form.addWidget(self.preview)
        self.preview_controller=PreviewController(self);self.preview_controller.ready.connect(self.preview_ready);self.preview_image=None
        self.path=QTextEdit(); self.path.setReadOnly(True); self.path.setMaximumHeight(100); form.addWidget(self.path)
        form.addWidget(QLabel('备注')); self.note=QTextEdit(); self.note.setMaximumHeight(140); form.addWidget(self.note)
        form.addWidget(QLabel('标签（逗号分隔）')); self.tags=QLineEdit(); form.addWidget(self.tags)
        self.favorite=QCheckBox('收藏此文件'); form.addWidget(self.favorite)
        self.edit_status=QLabel('未修改'); form.addWidget(self.edit_status)
        self.note.textChanged.connect(self.edit_changed)
        self.tags.textChanged.connect(self.edit_changed)
        self.favorite.toggled.connect(self.edit_changed)
        actions=QHBoxLayout(); form.addLayout(actions); self.button(actions,'保存备注',self.save_note); self.button(actions,'打开文件',self.open_file)
        self.button(form,'打开所在文件夹',self.reveal); self.button(form,'复制路径',lambda:QApplication.clipboard().setText(self.path.toPlainText())); form.addStretch(); splitter.addWidget(detail); splitter.setSizes([240,850,320])
        self.tree.itemSelectionChanged.connect(self.nav_changed); self.tree.itemDoubleClicked.connect(self.alias_dialog)
        self.table.selectionModel().selectionChanged.connect(self.selection_changed); self.table.doubleClicked.connect(lambda _:self.open_file())
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu); self.table.customContextMenuRequested.connect(self.context_menu)
        self.timer=QTimer(); self.timer.setSingleShot(True); self.timer.setInterval(220); self.timer.timeout.connect(self.reload)
        for w in [self.query,self.start,self.end,self.tag_filter]: w.textChanged.connect(lambda:self.timer.start())
        for w in [self.minimum,self.maximum]: w.valueChanged.connect(lambda:self.timer.start())
        self.category.currentIndexChanged.connect(self.reload); self.account.currentIndexChanged.connect(self.rebuild_tree)
        self.model.sortRequested.connect(self.sort_changed)
        self.tree.itemExpanded.connect(self.expand_directory)
        self.monitor=None;self.duplicate_dialog=None;self.statistics_dialog=None;self.task_kind=''
        self.monitor_signals=MonitorSignals(self);self.monitor_signals.updated.connect(self.monitor_updated);self.monitor_signals.status.connect(self.monitor_status)
        self.monitor_label=QLabel('空闲 · 自动监控未开启');self.monitor_label.setMaximumWidth(480);self.monitor_label.setTextFormat(Qt.TextFormat.PlainText);self.statusBar().addPermanentWidget(self.monitor_label)
        self.update_accounts(); self.rebuild_tree()
        if auto: QTimer.singleShot(500,self.startup)

    def button(self,layout,text,fn):
        b=QPushButton(text); b.clicked.connect(fn); layout.addWidget(b); return b

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
        self.tree.blockSignals(True); self.tree.clear()
        def item(parent,title,data):
            i=QTreeWidgetItem(parent,[title]); i.setData(0,Qt.ItemDataRole.UserRole,data); return i
        counts=self.store.category_counts(self.account.currentData() or '')
        all_item=item(self.tree,f'全部文件 ({sum(c["count"] for c in counts.values()):,})',{})
        item(self.tree,'最近文件（7 天）',{'recent':True})
        smart=item(self.tree,'智能管理',{})
        item(smart,'重复文件',{'duplicates':True});item(smart,'大文件',{'large':True});item(smart,'存储统计',{'statistics':True});smart.setExpanded(True)
        for cat in [*CATEGORIES,'其他文件']: item(self.tree,f'{cat} ({counts.get(cat,{}).get("count",0):,})',{'category':cat})
        item(self.tree,'★ 收藏',{'favorite':True})
        tag_root=item(self.tree,'我的标签（双击管理）',{'tags_view':True})
        for tag,count in sorted(self.store.tags().items()):item(tag_root,f'{tag} ({count:,})',{'tag':tag,'exact_tag':True})
        item(self.tree,'已不存在的文件',{'missing':True})
        raw=item(self.tree,'微信原始目录（双击可设置别名）',{'raw':True}); self.directory_data={}
        selected=self.account.currentData()
        for a in self.store.accounts():
            if selected and selected!=a['path']:continue
            root_item=item(raw,a['name'],{'directory':a['path'],'account_edit':True}); nodes={a['path']:root_item}
            root_item.setToolTip(0,a['path'])
            info=self.store.directory_info(a['path'])
            if info:self.directory_data[a['path']]=info
            QTreeWidgetItem(root_item,['展开以加载目录…'])
        raw.setExpanded(True); self.tree.setCurrentItem(all_item); self.nav={}; self.tree.blockSignals(False); self.reload()

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
            label=d['alias'] or LABELS.get(p.name,p.name)
            if not d['alias'] and len(p.name)==7 and p.name[4]=='-':label=p.name[:4]+'年'+p.name[5:]+'月'
            node=QTreeWidgetItem(item,[f'{label} ({d["count"]:,})'])
            node.setData(0,Qt.ItemDataRole.UserRole,{'directory':d['path'],'label':label})
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
        else:self.store.alias(path,name.strip())
        self.rebuild_tree()

    def reload(self,*args,preserve=False):
        if not self.confirm_pending(): return
        selected_paths=[r['path'] for r in self.selected()] if preserve else []
        scroll=self.table.verticalScrollBar().value() if preserve else 0
        for w in [self.start,self.end]:
            text=w.text().strip()
            if text:
                try: datetime.strptime(text,'%Y-%m-%d')
                except ValueError:self.statusBar().showMessage('日期格式应为 YYYY-MM-DD'); return
        if self.start.text() and self.end.text() and self.start.text()>self.end.text():
            self.statusBar().showMessage('起始日期不能晚于结束日期。');return
        if self.maximum.value() and self.maximum.value()<self.minimum.value():
            self.statusBar().showMessage('大小上限不能小于下限。');return
        filters=dict(query=self.query.text().strip(),category=self.nav.get('category') or (self.category.currentText() if self.category.currentIndex()>0 else ''),account=self.account.currentData() or '',favorite=self.nav.get('favorite',False),tag=self.nav.get('tag') or self.tag_filter.text().strip(),exact_tag=self.nav.get('exact_tag',False),minimum=int(self.minimum.value()*1024**2),maximum=int(self.maximum.value()*1024**2) if self.maximum.value() else None,start=self.start.text().strip(),end=self.end.text().strip(),directory=self.nav.get('directory',''),missing=self.nav.get('missing',False))
        if self.nav.get('recent'):
            from datetime import timedelta
            filters['start']=(datetime.now()-timedelta(days=7)).strftime('%Y-%m-%d')
        page=self.store.search_page(order=self.sort_order,descending=self.sort_desc,**filters)
        rows=page.rows
        self.preview_controller.clear();self.preview_image=None
        self.active=None; self.model.configure(self.store,filters,self.sort_order,self.sort_desc,page); self.info.setText('选择文件查看详情'); self.path.clear(); self.note.clear(); self.tags.clear(); self.preview.clear(); self.favorite.setChecked(False)
        d=self.directory_data.get(self.nav.get('directory'))
        text=f'共 {page.total:,} 个可管理文件 · {human(page.size)} · 首批 {len(rows)} 个，向下滚动加载更多'
        if d:text+=f' | 原目录含内部数据：{d["count"]:,} 个文件 / {human(d["size"])}'
        self.statusBar().showMessage(text)
        if not rows:self.info.setText('没有匹配的文件。请调整筛选条件，或添加微信目录并刷新索引。')
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
        selected=self.selected(); self.statusBar().showMessage(f'当前 {len(self.model.rows):,} 个文件 · 选中 {len(selected)} 个 · {human(sum(r["size"] for r in selected))}')
        if not selected:return
        r=selected[0]; self.active=r; self.info.setText(f'{r["name"]}\n{r["category"]} · {human(r["size"])}\n账号：{r["account_name"]}'+('\n文件已不存在' if r['missing'] else '')); self.path.setPlainText(r['path']); self.note.setPlainText(r['note']); self.tags.setText(r['tags']); self.favorite.setChecked(bool(r['favorite'])); self.preview.clear()
        self.preview_controller.clear();self.preview_image=None
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
        m=QMenu(self); m.addAction('打开文件',self.open_file); m.addAction('打开所在文件夹',self.reveal); m.addAction('复制路径',lambda:QApplication.clipboard().setText(self.path.toPlainText())); m.addAction('复制 / 导出所选',self.export); m.addAction('批量添加标签',self.batch_tags);m.addAction('批量管理所选',lambda:self.bulk_dialog(False));m.addAction('批量管理当前筛选结果',lambda:self.bulk_dialog(True)); m.exec(self.table.viewport().mapToGlobal(pos))

    def start_worker(self,fn,done,scan=False):
        if self.worker and self.worker.isRunning():QMessageBox.information(self,'任务运行中','请等待当前任务完成。'); return
        self.scan_button.setEnabled(False); self.add_button.setEnabled(False); self.stop_button.setEnabled(scan)
        self.progress_bar.show()
        self.worker=Worker(fn); self.worker.progress.connect(self.update_progress)
        self.worker.done.connect(done); self.worker.finished.connect(self.task_finished); self.worker.start()

    def update_progress(self,text):
        self.progress_label.setText(text);self.statusBar().showMessage(text)

    def task_finished(self):self.scan_button.setEnabled(True); self.add_button.setEnabled(True); self.stop_button.setEnabled(False);self.progress_bar.hide()

    def scan(self):
        if not self.confirm_pending(): return
        self.task_kind='scan'
        self.statusBar().showMessage('开始扫描…')
        self.start_worker(lambda progress:self.store.scan(progress,lambda:QThread.currentThread().isInterruptionRequested()),self.scan_done,True)

    def scan_done(self,out):
        self.rebuild_tree()
        if 'error' in out:
            self.store.set_setting('state:scan',{'complete':False,'running':False,'errors':[out['error']]});QMessageBox.warning(self,'扫描失败',out['error']); return
        r=out['result']; self.statusBar().showMessage(f'扫描'+('已停止' if r['cancelled'] else '完成')+f'：{r["files"]:,} 个可管理文件；{len(r["errors"])} 个访问异常')
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
        if selected:self.nav={'tag':selected[0],'exact_tag':True};self.reload()

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
        action,ok=QInputDialog.getItem(self,'设置与数据','选择操作',['备份索引、备注和收藏','恢复备份','开启/关闭自动监控','重新启动自动监控','查看本地数据位置','关于与许可证'],0,False)
        if not ok:return
        if action.startswith('备份'):
            target,_=QFileDialog.getSaveFileName(self,'备份数据','微信文件管理器备份.sqlite','SQLite (*.sqlite)')
            if not target:return
            if canonical(target)==canonical(self.store.path) or any(Path(target).resolve().is_relative_to(Path(root).resolve()) for root in self.store.source_roots()):QMessageBox.warning(self,'无法备份','请选择微信原目录和当前数据库以外的位置。'); return
            try:self.store.backup(target); QMessageBox.information(self,'备份完成',target)
            except Exception as e:QMessageBox.warning(self,'备份失败',str(e))
        elif action=='恢复备份': self.restore_backup()
        elif action=='开启/关闭自动监控':
            enabled=not self.store.setting('monitor:enabled',False);self.store.set_setting('monitor:enabled',enabled)
            if enabled:self.start_monitor()
            elif self.monitor:self.monitor.stop()
        elif action=='重新启动自动监控':self.store.set_setting('monitor:enabled',True);self.restart_monitor()
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
            rollback=self.store.restore(source);self.active=None;self.update_accounts();self.rebuild_tree()
            QMessageBox.information(self,'恢复完成','恢复成功。原数据自动备份至：\n'+str(rollback))
        except Exception as e:QMessageBox.warning(self,'恢复失败',str(e))
        finally:
            if self.store.setting('monitor:enabled',False):self.start_monitor()

    def export_done(self,out):
        if 'error' in out:QMessageBox.warning(self,'导出失败',out['error']); return
        r=out['result']; QMessageBox.information(self,'复制结果',f'成功 {r["copied"]}；跳过 {r["skipped"]}；失败 {len(r["failures"])}\n清单：{r["manifest"]}\n'+'\n'.join(r['failures'][:10]))

    def show_duplicates(self):
        if self.duplicate_dialog is None:
            self.duplicate_dialog=DuplicatesDialog(self.store,self.run_duplicates,self.cancel_duplicates,self)
            self.duplicate_dialog.copyRequested.connect(self.export_rows)
        else:self.duplicate_dialog.refresh()
        self.duplicate_dialog.show();self.duplicate_dialog.raise_()

    def run_duplicates(self):
        if not self.confirm_pending():return
        if self.worker and self.worker.isRunning():QMessageBox.information(self,'任务运行中','请等待当前扫描、检测或导出完成。');return
        self.task_kind='duplicates'
        self.start_worker(lambda progress:self.store.detect_duplicates(progress,lambda:QThread.currentThread().isInterruptionRequested()),self.duplicates_done,True)

    def cancel_duplicates(self):
        if self.task_kind=='duplicates' and self.worker and self.worker.isRunning():self.worker.requestInterruption()

    def duplicates_done(self,out):
        if self.duplicate_dialog:self.duplicate_dialog.refresh()
        if 'error' in out:
            self.store.set_setting('state:duplicates',{'complete':False,'running':False,'errors':[out['error']]});QMessageBox.warning(self,'重复检测失败',out['error']);return
        r=out['result'];self.progress_label.setText(f'重复检测：'+('已取消' if r['cancelled'] else '已完成')+f'；计算 {r["hashed"]}，缓存 {r["cache_hits"]}，跳过 {r["skipped"]}')
        if r['errors']:QMessageBox.warning(self,'检测有跳过项','结果不完整，可等待文件稳定后重试：\n'+'\n'.join(r['errors'][:12]))
        if self.statistics_dialog and self.statistics_dialog.isVisible():self.statistics_dialog.refresh()

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
        if message['result'].get('cancelled'):return
        if self.is_dirty():self.statusBar().showMessage('索引已自动更新；当前有未保存修改，保存或刷新后查看新列表。');return
        self.reload(preserve=True)
        counts=self.store.category_counts(self.account.currentData() or '')
        for i in range(self.tree.topLevelItemCount()):
            item=self.tree.topLevelItem(i);data=item.data(0,Qt.ItemDataRole.UserRole) or {}
            if data.get('category'):item.setText(0,f'{data["category"]} ({counts.get(data["category"],{}).get("count",0):,})')
            elif not data and item.text(0).startswith('全部文件'):item.setText(0,f'全部文件 ({sum(c["count"] for c in counts.values()):,})')
        if self.statistics_dialog and self.statistics_dialog.isVisible():self.statistics_dialog.refresh()
        if self.duplicate_dialog and self.duplicate_dialog.isVisible():self.duplicate_dialog.refresh()

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

    def closeEvent(self,event):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption(); QMessageBox.information(self,'任务仍在运行','已请求停止扫描。请等待当前扫描或复制完成后关闭。'); event.ignore()
        elif self.confirm_pending():
            if self.monitor and not self.monitor.stop():event.ignore();return
            if self.duplicate_dialog:self.duplicate_dialog.close()
            if self.statistics_dialog:self.statistics_dialog.close()
            event.accept()
        else:event.ignore()
