"""Metadata filtering and bounded, deterministic SQL pagination."""
import os
from dataclasses import dataclass
from app.paths import canonical

@dataclass
class Page:
    rows: list
    total: int
    size: int

class SearchMixin:
    @staticmethod
    def _where(query='',category='',account='',favorite=False,tag='',minimum=0,maximum=None,start='',end='',directory='',missing=False,exact_tag=False):
        clauses=['f.missing=?'];args=[int(missing)]
        if query:
            clauses.append('(instr(lower(f.name),lower(?))>0 OR instr(lower(f.note),lower(?))>0 OR instr(lower(f.tags),lower(?))>0)');args += [query]*3
        for column,value in [('category',category),('account',account)]:
            if value:clauses.append('f.'+column+'=?');args.append(value)
        if favorite:clauses.append('f.favorite=1')
        if tag:
            clauses.append("instr(','||replace(f.tags, ', ', ',')||',', ','||?||',')>0" if exact_tag else 'instr(lower(f.tags),lower(?))>0');args.append(tag)
        clauses.append('f.size>=?');args.append(minimum)
        if maximum is not None:clauses.append('f.size<=?');args.append(maximum)
        if start:clauses.append("date(f.mtime,'unixepoch','localtime')>=?");args.append(start)
        if end:clauses.append("date(f.mtime,'unixepoch','localtime')<=?");args.append(end)
        if directory:
            prefix=canonical(directory)+os.sep;clauses.append('substr(f.path,1,?)=?');args += [len(prefix),prefix]
        return ' AND '.join(clauses),args

    def search(self,query='',category='',account='',favorite=False,tag='',minimum=0,maximum=None,start='',end='',directory='',missing=False,**extra):
        return self.search_page(limit=None,query=query,category=category,account=account,favorite=favorite,tag=tag,minimum=minimum,maximum=maximum,start=start,end=end,directory=directory,missing=missing,**extra).rows

    def search_page(self,limit=200,offset=0,order='mtime',descending=True,count=True,**filters):
        if order not in {'name','category','size','mtime','account_name','tags','favorite'}:raise ValueError('不支持的排序字段')
        if offset<0 or (limit is not None and not 1<=limit<=1000):raise ValueError('分页范围无效')
        where,args=self._where(**filters)
        join=' FROM files f JOIN accounts a ON a.path=f.account WHERE '+where
        column='a.name' if order=='account_name' else 'f.'+order
        sql='SELECT f.*,a.name account_name'+join+' ORDER BY '+column+(' DESC' if descending else ' ASC')+',f.path ASC'
        params=list(args)
        if limit is not None:sql+=' LIMIT ? OFFSET ?';params += [limit,offset]
        with self.connect() as db:
            total,size=db.execute('SELECT count(*),coalesce(sum(f.size),0)'+join,args).fetchone() if count else (-1,0)
            rows=[dict(r) for r in db.execute(sql,params)]
        return Page(rows,total,size)

    def category_counts(self,account=''):
        sql='SELECT category,count(*),sum(size) FROM files WHERE missing=0';args=[]
        if account:sql+=' AND account=?';args=[account]
        with self.connect() as db:return {r[0]:{'count':r[1],'size':r[2]} for r in db.execute(sql+' GROUP BY category',args)}

    def directory_children(self,parent,limit=200,offset=0):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM directories WHERE parent=? ORDER BY path LIMIT ? OFFSET ?',(canonical(parent),limit,offset))]

    def directory_info(self,path):
        with self.connect() as db:
            row=db.execute('SELECT * FROM directories WHERE path=?',(canonical(path),)).fetchone()
            return dict(row) if row else None
