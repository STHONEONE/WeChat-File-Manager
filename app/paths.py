import os
import re
import stat
from datetime import datetime
from pathlib import Path

CATEGORIES = {'文档': 'pdf doc docx xls xlsx ppt pptx txt md rtf csv odt pdg', '图片': 'jpg jpeg png gif bmp webp tif tiff ico', '视频': 'mp4 avi mov mkv wmv flv webm', '音频': 'mp3 wav flac aac ogg m4a amr silk', '压缩文件': 'zip rar 7z tar gz bz2'}
EXTENSIONS = {'.'+ext: cat for cat, exts in CATEGORIES.items() for ext in exts.split()}
SYSTEM = {'all_users','backup','db_storage','apm_record','business','resource','cache','temp','tmp','logs','log','config','mmkv','thumb','thumbs','.thumbnails','favorite','emoticon','sns','xweb','xeditor'}
INTERNAL = {'.dat','.db','.db-wal','.db-shm','.mmkv','.crc','.kvdb','.ini','.lock','.tmp','.bak','.sqlite','.thumb','.xml'}
LABELS = {'msg':'聊天文件','file':'收到的文件','attach':'聊天附件（部分加密）','video':'聊天视频','db_storage':'聊天数据库（仅统计）','cache':'缓存（仅统计）','config':'配置（仅统计）','temp':'临时文件（仅统计）','business':'业务数据（仅统计）','resource':'资源（仅统计）','apm_record':'运行记录（仅统计）','FileStorage':'聊天资源','Image':'图片','Video':'视频','File':'收到的文件'}

def canonical(path):
    return os.path.normcase(os.path.abspath(path))

def linked(path):
    try:
        s = os.lstat(path)
        return stat.S_ISLNK(s.st_mode) or bool(getattr(s, 'st_file_attributes', 0) & 0x400)
    except OSError:
        return True

def discover(root):
    p = Path(root).absolute()
    if linked(p):
        return []
    def account(d):
        return (d/'msg').is_dir() or (d/'FileStorage').is_dir()
    if account(p):
        return [p]
    try:
        return [d for d in p.iterdir() if d.is_dir() and not linked(d) and account(d)]
    except OSError:
        return []

def candidates():
    roots = [Path('D:/xwechat_files')]
    for base in [Path.home(), Path.home()/'Documents', Path(os.environ.get('OneDrive', str(Path.home())))/'Documents']:
        roots += [base/n for n in ('xwechat_files','WeChat Files','Weixin Files')]
    return list(dict.fromkeys(str(p) for p in roots if p.is_dir()))

def month_of(path, mtime):
    # Adapted from oracis/wechat-file-organizer-gui month_of (MIT).
    for part in reversed(Path(path).parts[:-1]):
        if re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', part):
            return part
    return datetime.fromtimestamp(mtime).strftime('%Y-%m')

def human(n):
    for unit in ('B','KiB','MiB','GiB','TiB'):
        if n < 1024 or unit == 'TiB': return f'{n:,.1f} {unit}'
        n /= 1024

