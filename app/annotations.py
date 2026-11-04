"""Annotation and tag operations; never writes a source file."""
def tags_from(text):
    return list(dict.fromkeys(t.strip() for t in text.replace('，',',').split(',') if t.strip()))

def checked_tag(name):
    name=name.strip()
    if not name or ',' in name or '，' in name or '\n' in name:raise ValueError('标签不能为空，且不能包含逗号或换行。')
    return name

class AnnotationMixin:
    def bulk_manage(self,operation,tags='',paths=None,filters=None,cancelled=lambda:False):
        if operation not in {'add_tags','remove_tags','favorite','unfavorite'}:raise ValueError('不支持的批量操作')
        names=[checked_tag(t) for t in tags_from(tags)]
        if operation in {'add_tags','remove_tags'} and not names:raise ValueError('请指定至少一个标签')
        class Cancelled(Exception):pass
        result={'success':0,'changed':0,'failures':[],'cancelled':False}
        try:
            with self.connect() as db:
                if paths is None:
                    where,args=self._where(**(filters or {}))
                    paths=[r[0] for r in db.execute('SELECT f.path FROM files f JOIN accounts a ON a.path=f.account WHERE '+where,args)]
                if operation=='add_tags':db.executemany('INSERT OR IGNORE INTO tag_catalog(name) VALUES (?)',[(t,) for t in names])
                for path in dict.fromkeys(paths):
                    if cancelled():raise Cancelled()
                    row=db.execute('SELECT tags,favorite FROM files WHERE path=?',(path,)).fetchone()
                    if row is None:result['failures'].append(path+'：文件不在索引中');continue
                    if operation in {'add_tags','remove_tags'}:
                        old=tags_from(row['tags'])
                        new=list(dict.fromkeys(old+names)) if operation=='add_tags' else [t for t in old if t not in names]
                        value=', '.join(new)
                        if value!=row['tags']:db.execute('UPDATE files SET tags=? WHERE path=?',(value,path));result['changed']+=1
                    else:
                        value=int(operation=='favorite')
                        if value!=row['favorite']:db.execute('UPDATE files SET favorite=? WHERE path=?',(value,path));result['changed']+=1
                    result['success']+=1
        except Cancelled:return dict(success=0,changed=0,failures=[],cancelled=True)
        return result

    def annotate(self,path,note,tags,favorite):
        names=tags_from(tags)
        with self.connect() as db:
            db.execute('UPDATE files SET note=?,tags=?,favorite=? WHERE path=?',(note,', '.join(names),int(favorite),path))
            db.executemany('INSERT OR IGNORE INTO tag_catalog(name) VALUES (?)',[(t,) for t in names])

    def tags(self):
        with self.connect() as db:
            names={r[0]:0 for r in db.execute('SELECT name FROM tag_catalog')}
            for row in db.execute('SELECT tags FROM files WHERE missing=0'):
                for tag in tags_from(row[0]):names[tag]=names.get(tag,0)+1
        return names

    def create_tag(self,name):
        name=checked_tag(name)
        with self.connect() as db:db.execute('INSERT OR IGNORE INTO tag_catalog(name) VALUES (?)',(name,))

    def rename_tag(self,old,new):
        new=checked_tag(new)
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO tag_catalog(name) VALUES (?)',(new,))
            for row in db.execute('SELECT path,tags FROM files WHERE instr(tags,?)>0',(old,)).fetchall():
                tags=list(dict.fromkeys(new if t==old else t for t in tags_from(row['tags'])))
                db.execute('UPDATE files SET tags=? WHERE path=?',(', '.join(tags),row['path']))
            if old!=new:db.execute('DELETE FROM tag_catalog WHERE name=?',(old,))

    def delete_tag(self,name):
        with self.connect() as db:
            for row in db.execute('SELECT path,tags FROM files WHERE instr(tags,?)>0',(name,)).fetchall():
                db.execute('UPDATE files SET tags=? WHERE path=?',(', '.join(t for t in tags_from(row['tags']) if t!=name),row['path']))
            db.execute('DELETE FROM tag_catalog WHERE name=?',(name,))

    def add_tags(self,paths,tags):
        names=[checked_tag(t) for t in tags_from(tags)]
        with self.connect() as db:
            db.executemany('INSERT OR IGNORE INTO tag_catalog(name) VALUES (?)',[(t,) for t in names])
            for path in dict.fromkeys(paths):
                row=db.execute('SELECT tags FROM files WHERE path=?',(path,)).fetchone()
                if row:db.execute('UPDATE files SET tags=? WHERE path=?',(', '.join(dict.fromkeys(tags_from(row[0])+names)),path))
