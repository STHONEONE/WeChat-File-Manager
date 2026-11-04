from datetime import datetime
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QTabWidget,QTreeWidget,QTreeWidgetItem,QProgressBar
from app.statistics import storage_statistics
from app.paths import human
from app.ui.duplicates import open_path,locate

class StatisticsDialog(QDialog):
    def __init__(self,store,parent=None):
        super().__init__(parent);self.store=store;self.setWindowTitle('存储统计 · 元数据快照');self.resize(1120,760)
        layout=QVBoxLayout(self);self.summary=QLabel();self.summary.setWordWrap(True);layout.addWidget(self.summary)
        refresh=QPushButton('刷新统计');refresh.clicked.connect(self.refresh);layout.addWidget(refresh)
        self.tabs=QTabWidget();layout.addWidget(self.tabs)
        self.categories=self.table('分类分布',['类别','文件数','大小','容量占比'])
        self.accounts=self.table('微信账号',['账号','文件数','可管理文件大小','最近扫描尝试','状态'])
        self.largest=self.table('大文件前 100',['文件名','大小','账号','原始路径'])
        self.directories=self.table('主要目录前 100',['目录','账号','总文件数','元数据总大小','原始路径'])
        row=QHBoxLayout();layout.addLayout(row)
        for label,callback in [('打开选中大文件',self.open),('定位选中大文件',self.locate)]:
            b=QPushButton(label);b.clicked.connect(callback);row.addWidget(b)
        self.largest.itemDoubleClicked.connect(self.open);self.refresh()
    def table(self,title,headers):
        table=QTreeWidget();table.setHeaderLabels(headers);self.tabs.addTab(table,title);return table
    def refresh(self):
        s=storage_statistics(self.store);d=s['duplicates'];state=d['state'];scan=s['scan']
        stamp=datetime.fromtimestamp(scan['time']).strftime('%Y-%m-%d %H:%M:%S') if scan.get('time') else '未完成'
        self.summary.setText(f'可管理文件 {s["count"]:,} 个 / {human(s["size"])}；已确认重复 {d["groups"]:,} 组，理论冗余 {human(d["redundant"])}。\n扫描记录：{stamp}（'+('完整' if scan.get('complete') else '进行中 / 不完整 / 有访问异常')+'）；哈希覆盖 '+str(s['verified'])+' 个文件（'+('最近候选检测已完成' if state.get('complete') else '候选检测未完成 / 有跳过项')+'）。\n分类与账号数据仅包含可管理文件；内部目录总量来自最近完整扫描，监控只更新可管理文件元数据。理论冗余不代表实际可释放空间。')
        self.summary.setText(self.summary.text()+'\n监控状态：'+s['monitor'].get('text','未开启'))
        for table in (self.categories,self.accounts,self.largest,self.directories):table.clear()
        for c in s['categories']:
            item=QTreeWidgetItem(self.categories,[c['category'],str(c['count']),human(c['size']),'']);bar=QProgressBar();bar.setValue(round(100*c['size']/max(s['size'],1)));self.categories.setItemWidget(item,3,bar)
        for a in s['accounts']:
            stamp=datetime.fromtimestamp(a['scanned_at']).strftime('%Y-%m-%d %H:%M:%S') if a['scanned_at'] else '未扫描'
            QTreeWidgetItem(self.accounts,[a['name'],str(a['count']),human(a['size']),stamp,'完整' if a['complete'] else '未完成 / 异常'])
        for f in s['largest']:
            item=QTreeWidgetItem(self.largest,[f['name'],human(f['size']),f['account_name'],f['path']]);item.setData(0,Qt.ItemDataRole.UserRole,f)
        for d in s['directories']:QTreeWidgetItem(self.directories,[d['alias'] or d['path'].split('\\')[-1],d['account_name'],str(d['count']),human(d['size']),d['path']])
    def open(self,*args):
        rows=self.largest.selectedItems()
        if rows:open_path(rows[0].data(0,Qt.ItemDataRole.UserRole)['path'],self)
    def locate(self):
        rows=self.largest.selectedItems()
        if rows:locate(rows[0].data(0,Qt.ItemDataRole.UserRole)['path'])
