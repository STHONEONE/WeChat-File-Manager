from datetime import datetime
from PySide6.QtCore import Qt,QAbstractTableModel,QModelIndex,Signal
from app.paths import human

class FilesModel(QAbstractTableModel):
    sortRequested=Signal(int,object)
    columns=['文件名','类型','大小','修改时间','所属账号','标签','收藏']
    def __init__(self):
        super().__init__(); self.rows=[];self.store=None;self.total=0;self.filters={};self.order='mtime';self.descending=True
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

    def configure(self,store,filters,order,descending,page):
        self.beginResetModel()
        self.store=store;self.filters=filters;self.order=order;self.descending=descending
        self.rows=page.rows;self.total=page.total
        self.endResetModel()

    def canFetchMore(self,parent=QModelIndex()):
        return not parent.isValid() and self.store is not None and len(self.rows)<self.total

    def fetchMore(self,parent=QModelIndex()):
        if not self.canFetchMore(parent):return
        rows=self.store.search_page(offset=len(self.rows),count=False,order=self.order,descending=self.descending,**self.filters).rows
        if not rows:self.total=len(self.rows);return
        first=len(self.rows);self.beginInsertRows(QModelIndex(),first,first+len(rows)-1);self.rows.extend(rows);self.endInsertRows()

    def sort(self,column,order=Qt.SortOrder.AscendingOrder):
        self.sortRequested.emit(column,order)

