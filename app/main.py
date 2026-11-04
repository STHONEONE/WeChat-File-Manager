import json
import os
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QAbstractTableModel, QModelIndex, QSortFilterProxyModel, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QImageReader, QPixmap, QIcon, QPainter, QColor, QFontDatabase, QFont
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QLineEdit,QComboBox,QPushButton,QSplitter,QTreeWidget,QTreeWidgetItem,QTableView,QLabel,QTextEdit,QCheckBox,QFormLayout,QFileDialog,QMessageBox,QInputDialog,QMenu,QDoubleSpinBox,QDialog,QDialogButtonBox)
from app.core import Store, CATEGORIES, LABELS, candidates, canonical, human, export_files

class Worker(QThread):
    progress=Signal(str)
    done=Signal(object)
    def __init__(self, fn):
        super().__init__(); self.fn=fn
    def run(self):
        try: self.done.emit({'result':self.fn(self.progress.emit)})
        except Exception as e: self.done.emit({'error':str(e)})

class FilesModel(QAbstractTableModel):
    columns=['文件名','类型','大小','修改时间','所属账号','标签','收藏']
    def __init__(self): super().__init__(); self.rows=[]
    def rowCount(self,parent=QModelIndex()): return 0 if parent.isValid() else len(self.rows)
    def columnCount(self,parent=QModelIndex()): return len(self.columns)
    def headerData(self,section,orientation,role=Qt.ItemDataRole.DisplayRole):
        if role==Qt.ItemDataRole.DisplayRole and orientation==Qt.Orientation.Horizontal: return self.columns[section]
    def data(self,index,role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid(): return None
        r=self.rows[index.row()]; col=index.column()
        if role==Qt.ItemDataRole.UserRole:
            return [r['name'].lower(),r['category'],r['size'],r['mtime'],r['account_name'],r['tags'],r['favorite']][col]
        if role==Qt.ItemDataRole.DisplayRole:
            return [r['name'],r['category'],human(r['size']),datetime.fromtimestamp(r['mtime']).strftime('%Y-%m-%d %H:%M'),r['account_name'],r['tags'],'★' if r['favorite'] else ''][col]
        if role==Qt.ItemDataRole.ToolTipRole: return r['path']+('（已不存在）' if r['missing'] else '')
    def replace(self,rows): self.beginResetModel(); self.rows=rows; self.endResetModel()

class Window(QMainWindow):
    def __init__(self,store, auto=True):
        super().__init__(); self.store=store; self.worker=None; self.active=None; self.nav={}; self.directory_data={}
        font=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/'msyh.ttc'
        if font.exists(): QFontDatabase.addApplicationFont(str(font))
        self.setFont(QFont('Microsoft YaHei',10))
        self.setStyleSheet('QWidget {font-family:"Microsoft YaHei";font-size:13px;} QLabel#title {font-size:26px;font-weight:600;color:#143b32;} QLabel#caption {color:#687a74;margin-bottom:10px;} QPushButton {padding:7px 10px;border:1px solid #cbd8d2;border-radius:5px;background:white;} QLineEdit,QComboBox,QDoubleSpinBox,QTextEdit {padding:6px;border:1px solid #d3ded8;border-radius:4px;} QHeaderView::section {padding:8px;background:#eaf1ed;}')
        self.setWindowTitle('微信文件管理器 1.0'); self.resize(1440,900)
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
        self.start=QLineEdit(); self.start.setPlaceholderText('起始日期 YYYY-MM-DD')
        self.end=QLineEdit(); self.end.setPlaceholderText('结束日期 YYYY-MM-DD')
        self.minimum=QDoubleSpinBox(); self.minimum.setRange(0,1e9); self.minimum.setSuffix(' MiB 起')
        self.maximum=QDoubleSpinBox(); self.maximum.setRange(0,1e9); self.maximum.setSuffix(' MiB 止（0=不限）')
        self.tag_filter=QLineEdit(); self.tag_filter.setPlaceholderText('标签筛选')
        for w in [self.start,self.end,self.minimum,self.maximum,self.tag_filter]: filters.addWidget(w)
        self.button(filters,'统计',self.statistics); self.button(filters,'复制 / 导出所选',self.export)
        splitter=QSplitter(); layout.addWidget(splitter,1)
        self.tree=QTreeWidget(); self.tree.setHeaderLabel('文件导航'); splitter.addWidget(self.tree)
        self.model=FilesModel(); self.proxy=QSortFilterProxyModel(); self.proxy.setSourceModel(self.model); self.proxy.setSortRole(Qt.ItemDataRole.UserRole)
        self.table=QTableView(); self.table.setModel(self.proxy); self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows); self.table.setSelectionMode(QTableView.SelectionMode.ExtendedSelection); self.table.setSortingEnabled(True); self.table.setAlternatingRowColors(True); self.table.verticalHeader().hide(); self.table.setColumnWidth(0,360); self.table.setColumnWidth(3,155); splitter.addWidget(self.table)
        detail=QWidget(); form=QVBoxLayout(detail); self.info=QLabel('选择文件查看详情'); self.info.setWordWrap(True); self.info.setTextFormat(Qt.TextFormat.PlainText); self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); form.addWidget(self.info)
        self.preview=QLabel('图片预览'); self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter); self.preview.setMinimumHeight(180); form.addWidget(self.preview)
        self.path=QTextEdit(); self.path.setReadOnly(True); self.path.setMaximumHeight(100); form.addWidget(self.path)
        form.addWidget(QLabel('备注')); self.note=QTextEdit(); self.note.setMaximumHeight(140); form.addWidget(self.note)
        form.addWidget(QLabel('标签（逗号分隔）')); self.tags=QLineEdit(); form.addWidget(self.tags)
        self.favorite=QCheckBox('收藏此文件'); form.addWidget(self.favorite)
        actions=QHBoxLayout(); form.addLayout(actions); self.button(actions,'保存备注',self.save_note); self.button(actions,'打开文件',self.open_file)
        self.button(form,'打开所在文件夹',self.reveal); self.button(form,'复制路径',lambda:QApplication.clipboard().setText(self.path.toPlainText())); form.addStretch(); splitter.addWidget(detail); splitter.setSizes([240,850,320])
        self.tree.itemSelectionChanged.connect(self.nav_changed); self.tree.itemDoubleClicked.connect(self.alias_dialog)
        self.table.selectionModel().selectionChanged.connect(self.selection_changed); self.table.doubleClicked.connect(lambda _:self.open_file())
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu); self.table.customContextMenuRequested.connect(self.context_menu)
        self.timer=QTimer(); self.timer.setSingleShot(True); self.timer.setInterval(220); self.timer.timeout.connect(self.reload)
        for w in [self.query,self.start,self.end,self.tag_filter]: w.textChanged.connect(lambda:self.timer.start())
        for w in [self.minimum,self.maximum]: w.valueChanged.connect(lambda:self.timer.start())
        self.category.currentIndexChanged.connect(self.reload); self.account.currentIndexChanged.connect(self.rebuild_tree)
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
        if self.store.accounts(): self.scan()
        else: self.statusBar().showMessage('请添加微信文件目录，例如 D:\\xwechat_files')

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
        all_item=item(self.tree,'全部文件',{})
        for cat in [*CATEGORIES,'其他文件']: item(self.tree,cat,{'category':cat})
        item(self.tree,'★ 收藏',{'favorite':True}); item(self.tree,'我的标签',{'tags_view':True}); item(self.tree,'已不存在的文件',{'missing':True})
        raw=item(self.tree,'微信原始目录（双击可设置别名）',{'raw':True}); self.directory_data={}
        selected=self.account.currentData()
        for a in self.store.accounts():
            if selected and selected!=a['path']:continue
            root_item=item(raw,a['name'],{'directory':a['path'],'account_edit':True}); nodes={a['path']:root_item}
            for d in self.store.directories(a['path']):
                self.directory_data[d['path']]=d
                if d['path']==a['path']:continue
                p=Path(d['path']); label=d['alias'] or LABELS.get(p.name,p.name)
                if len(p.name)==7 and p.name[4]=='-': label=p.name[:4]+'年'+p.name[5:]+'月'
                if d['alias']:label=d['alias']
                n=item(nodes.get(canonical(p.parent),root_item),label,{'directory':d['path']}); n.setToolTip(0,f"{d['path']}\n{d['count']:,} 个文件 / {human(d['size'])}"); nodes[d['path']]=n
        raw.setExpanded(True); self.tree.setCurrentItem(all_item); self.nav={}; self.tree.blockSignals(False); self.reload()

    def nav_changed(self):
        items=self.tree.selectedItems(); self.nav=items[0].data(0,Qt.ItemDataRole.UserRole) if items else {}
        if self.nav.get('tags_view'):
            tags=sorted({t.strip() for r in self.store.search() for t in r['tags'].split(',') if t.strip()})
            tag,ok=QInputDialog.getItem(self,'我的标签','选择标签',tags,0,False) if tags else ('',False)
            if ok:self.tag_filter.setText(tag)
        self.reload()

    def alias_dialog(self,item,column):
        data=item.data(0,Qt.ItemDataRole.UserRole) or {}; path=data.get('directory')
        if not path:return
        name,ok=QInputDialog.getText(self,'自定义显示名称','只在本程序内生效：',text=item.text(0))
        if not ok or not name.strip():return
        if data.get('account_edit'):
            a=next(a for a in self.store.accounts() if a['path']==path)
            note,ok=QInputDialog.getMultiLineText(self,'账号备注','备注',a['note'])
            if not ok:return
            self.store.rename(path,name.strip(),note); self.update_accounts()
        else:self.store.alias(path,name.strip())
        self.rebuild_tree()

    def reload(self,*args):
        for w in [self.start,self.end]:
            text=w.text().strip()
            if text:
                try: datetime.strptime(text,'%Y-%m-%d')
                except ValueError:self.statusBar().showMessage('日期格式应为 YYYY-MM-DD'); return
        rows=self.store.search(query=self.query.text().strip(),category=self.nav.get('category') or (self.category.currentText() if self.category.currentIndex()>0 else ''),account=self.account.currentData() or '',favorite=self.nav.get('favorite',False),tag=self.tag_filter.text().strip(),minimum=int(self.minimum.value()*1024**2),maximum=int(self.maximum.value()*1024**2) if self.maximum.value() else None,start=self.start.text().strip(),end=self.end.text().strip(),directory=self.nav.get('directory',''),missing=self.nav.get('missing',False))
        self.active=None; self.model.replace(rows); self.info.setText('选择文件查看详情'); self.path.clear(); self.note.clear(); self.tags.clear(); self.preview.clear(); self.favorite.setChecked(False)
        d=self.directory_data.get(self.nav.get('directory'))
        text=f'当前 {len(rows):,} 个可管理文件 · {human(sum(r["size"] for r in rows))}'
        if d:text+=f' | 原目录含内部数据：{d["count"]:,} 个文件 / {human(d["size"])}'
        self.statusBar().showMessage(text)

    def selected(self):
        return [self.model.rows[self.proxy.mapToSource(i).row()] for i in self.table.selectionModel().selectedRows()]

    def selection_changed(self,*args):
        selected=self.selected(); self.statusBar().showMessage(f'当前 {len(self.model.rows):,} 个文件 · 选中 {len(selected)} 个 · {human(sum(r["size"] for r in selected))}')
        if not selected:return
        r=selected[0]; self.active=r; self.info.setText(f'{r["name"]}\n{r["category"]} · {human(r["size"])}\n账号：{r["account_name"]}'+('\n文件已不存在' if r['missing'] else '')); self.path.setPlainText(r['path']); self.note.setPlainText(r['note']); self.tags.setText(r['tags']); self.favorite.setChecked(bool(r['favorite'])); self.preview.clear()
        if r['category']=='图片' and not r['missing']:
            reader=QImageReader(r['path']); size=reader.size()
            if r['size']>40*1024**2 or size.width()*size.height()>60_000_000:self.preview.setText('图片过大，请使用关联程序打开'); return
            size.scale(300,240,Qt.AspectRatioMode.KeepAspectRatio); reader.setScaledSize(size); reader.setAutoTransform(True); img=reader.read()
            if img.isNull():self.preview.setText('无法预览此图片')
            else:self.preview.setPixmap(QPixmap.fromImage(img))
        else:self.preview.setText('使用系统关联程序打开；加密附件仅显示元数据')

    def save_note(self):
        if self.active:self.store.annotate(self.active['path'],self.note.toPlainText(),self.tags.text(),self.favorite.isChecked()); self.reload()

    def open_file(self):
        if not self.active:return
        p=Path(self.active['path'])
        if not p.is_file():QMessageBox.warning(self,'文件不可用','文件已不存在或无法访问，请刷新索引。'); return
        if p.suffix.lower() in {'.exe','.bat','.cmd','.ps1','.vbs','.js','.msi','.scr','.com','.lnk'}:
            if QMessageBox.question(self,'运行程序','此文件是可执行文件或脚本。是否调用系统打开？')!=QMessageBox.StandardButton.Yes:return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(p))):QMessageBox.warning(self,'打开失败','系统未能打开此文件，请检查文件关联。')

    def reveal(self):
        if self.active:QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.active['path']).parent)))

    def context_menu(self,pos):
        m=QMenu(self); m.addAction('打开文件',self.open_file); m.addAction('打开所在文件夹',self.reveal); m.addAction('复制路径',lambda:QApplication.clipboard().setText(self.path.toPlainText())); m.addAction('复制 / 导出所选',self.export); m.exec(self.table.viewport().mapToGlobal(pos))

    def start_worker(self,fn,done,scan=False):
        if self.worker and self.worker.isRunning():QMessageBox.information(self,'任务运行中','请等待当前任务完成。'); return
        self.scan_button.setEnabled(False); self.add_button.setEnabled(False); self.stop_button.setEnabled(scan)
        self.worker=Worker(fn); self.worker.progress.connect(self.statusBar().showMessage)
        self.worker.done.connect(done); self.worker.finished.connect(self.task_finished); self.worker.start()

    def task_finished(self):self.scan_button.setEnabled(True); self.add_button.setEnabled(True); self.stop_button.setEnabled(False)

    def scan(self):
        self.statusBar().showMessage('开始扫描…')
        self.start_worker(lambda progress:self.store.scan(progress,lambda:QThread.currentThread().isInterruptionRequested()),self.scan_done,True)

    def scan_done(self,out):
        self.rebuild_tree()
        if 'error' in out:QMessageBox.warning(self,'扫描失败',out['error']); return
        r=out['result']; self.statusBar().showMessage(f'扫描'+('已停止' if r['cancelled'] else '完成')+f'：{r["files"]:,} 个可管理文件；{len(r["errors"])} 个访问异常')
        if r['errors']:QMessageBox.warning(self,'部分目录无法读取','已保留未能完整扫描账号的旧文件状态。\n'+'\n'.join(r['errors'][:15]))

    def statistics(self):
        dirs=self.store.directories(); roots={a['path'] for a in self.store.accounts()}; rows=self.store.search(); lines=['全账号统计（包含内部文件的总量来自目录元数据）：']
        for a in self.store.accounts():
            d=next((d for d in dirs if d['path']==a['path']),None)
            if d:lines.append(f'{a["name"]}：{d["count"]:,} 个 / {human(d["size"])}')
        lines.append(f'可管理文件：{len(rows):,} 个 / {human(sum(r["size"] for r in rows))}')
        for c in [*CATEGORIES,'其他文件']:
            rs=[r for r in rows if r['category']==c]; lines.append(f'{c}：{len(rs):,} 个 / {human(sum(r["size"] for r in rs))}')
        QMessageBox.information(self,'文件统计','\n'.join(lines))

    def settings(self):
        action,ok=QInputDialog.getItem(self,'设置与数据','选择操作',['备份索引、备注和收藏','查看本地数据位置','关于与许可证'],0,False)
        if not ok:return
        if action.startswith('备份'):
            target,_=QFileDialog.getSaveFileName(self,'备份数据','微信文件管理器备份.sqlite','SQLite (*.sqlite)')
            if not target:return
            if canonical(target)==canonical(self.store.path) or any(Path(target).resolve().is_relative_to(Path(root).resolve()) for root in self.store.source_roots()):QMessageBox.warning(self,'无法备份','请选择微信原目录和当前数据库以外的位置。'); return
            try:self.store.backup(target); QMessageBox.information(self,'备份完成',target)
            except Exception as e:QMessageBox.warning(self,'备份失败',str(e))
        elif action.startswith('查看'):QMessageBox.information(self,'本地数据',str(self.store.path))
        else:QMessageBox.information(self,'关于','微信文件管理器 1.0\n目录识别和月份分类参考 oracis/wechat-file-organizer-gui (MIT)。\n本软件独立于微信，不解密聊天记录。\n开源许可见程序目录 licenses 文件夹。')

    def export(self):
        rows=self.selected()
        if not rows:QMessageBox.information(self,'选择文件','请先在列表中选择需要复制的文件。'); return
        target=QFileDialog.getExistingDirectory(self,'选择归档副本的保存目录')
        if not target:return
        mode,ok=QInputDialog.getItem(self,'归档方式','目录组织',['类型+月份','类型','月份','平铺'],0,False)
        if not ok:return
        conflict,ok=QInputDialog.getItem(self,'重名处理','目标存在同名文件时',['自动更名','跳过'],0,False)
        if not ok:return
        if QMessageBox.question(self,'确认复制',f'复制 {len(rows)} 个文件\n源目录：微信账号内的原始路径（详情栏可查看）\n目标：{target}\n方式：{mode}；重名：{conflict}\n仅创建副本，源文件保持原样。')!=QMessageBox.StandardButton.Yes:return
        self.start_worker(lambda progress:export_files(rows,target,mode,conflict,self.store.source_roots(),progress),self.export_done)

    def export_done(self,out):
        if 'error' in out:QMessageBox.warning(self,'导出失败',out['error']); return
        r=out['result']; QMessageBox.information(self,'复制结果',f'成功 {r["copied"]}；跳过 {r["skipped"]}；失败 {len(r["failures"])}\n清单：{r["manifest"]}\n'+'\n'.join(r['failures'][:10]))

    def closeEvent(self,event):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption(); QMessageBox.information(self,'任务仍在运行','已请求停止扫描。请等待当前扫描或复制完成后关闭。'); event.ignore()
        else:event.accept()

def main():
    app=QApplication(sys.argv); app.setApplicationName('WeChatFileManager'); app.setStyle('Fusion')
    asset_base=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1])); app.setWindowIcon(QIcon(str(asset_base/'assets'/'app.ico')))
    app.setStyleSheet('QWidget {font-family:"Microsoft YaHei UI";font-size:13px;} QMainWindow {background:#f5f7fa;} QLabel#title {font-size:26px;font-weight:600;color:#143b32;} QLabel#caption {color:#687a74;margin-bottom:10px;} QPushButton {padding:7px 12px;border:1px solid #cbd8d2;border-radius:5px;background:white;} QPushButton:hover {background:#e3f4ec;} QLineEdit,QComboBox,QDoubleSpinBox,QTextEdit {padding:6px;border:1px solid #d3ded8;border-radius:4px;background:white;} QTreeWidget,QTableView {border:1px solid #dce5df;background:white;selection-background-color:#c6ead8;selection-color:#123d30;} QHeaderView::section {padding:8px;background:#eaf1ed;border:0;}')
    data=Path(os.environ.get('WFM_DATA_DIR',str(Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'WeChatFileManager')))
    smoke='--smoke-test' in sys.argv
    store=Store(data/'index.sqlite'); window=Window(store,auto=not smoke); window.show()
    if smoke:
        def finish():
            window.grab().save(str(data/'smoke.png'))
            (data/'smoke.json').write_text(json.dumps({'rows':window.model.rowCount(),'qt_window_created':True}),encoding='utf-8')
            window.close(); app.quit()
        QTimer.singleShot(1000,finish)
    sys.exit(app.exec())

if __name__=='__main__':main()
