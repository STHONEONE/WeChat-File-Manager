"""Conservative, account-relative explanations; aliases never grant permissions."""
from pathlib import Path
from app.paths import canonical

# Anchored relative paths, not a guess based on any arbitrary folder's basename.
RULES={
 ('msg',):('聊天相关数据','包含当前账号的聊天相关资源；不表示这里包含全部历史记录。','mixed'),
 ('msg','file'):('聊天文件','新版微信的普通聊天文件目录，可包含文档及其他用户收发文件。','files'),
 ('msg','video'):('聊天视频','新版微信的视频资源目录；仅可识别的普通视频可进入删除流程。','videos'),
 ('msg','attach'):('聊天附件资源','可能包含加密附件、图片及其他会话资源；只展示和统计，不允许清理。','protected'),
 ('filestorage',):('旧版聊天资源','旧版微信的本地资源层级，具体用途取决于子目录。','mixed'),
 ('filestorage','file'):('旧版聊天文件','旧版微信收发的普通文件存储位置。','files'),
 ('filestorage','image'):('旧版图片资源','旧版微信图片资源；只对可识别的普通图片开放文件管理。','images'),
 ('filestorage','video'):('旧版视频资源','旧版微信视频资源；不保证包含所有历史视频。','videos'),
 ('db_storage',):('微信数据库相关目录','关键内部数据，只读展示与统计；不解密、不删除。','protected'),
 ('config',):('微信配置','关键内部配置，只读展示与统计。','protected'),
 ('cache',):('缓存','缓存数据只读展示；不提供一键清空或删除。','protected'),
 ('temp',):('临时数据','临时数据用途可能随版本变化，只读展示与统计。','protected'),
 ('business',):('业务内部数据','微信业务模块内部数据，只读展示与统计。','protected'),
 ('resource',):('微信资源数据','内部资源，只读展示与统计。','protected'),
 ('apm_record',):('运行记录','运行诊断相关目录，只读展示与统计。','protected'),
}
DELETE_PREFIXES={('msg','file'),('msg','video'),('filestorage','file'),('filestorage','image'),('filestorage','video')}
DELETE_EXTENSIONS=set(('.pdf .doc .docx .xls .xlsx .ppt .pptx .txt .md .rtf .csv .odt .jpg .jpeg .png .gif .bmp .webp .tif .tiff .ico .mp4 .avi .mov .mkv .wmv .flv .webm .mp3 .wav .flac .aac .ogg .m4a .amr .zip .rar .7z .tar .gz .bz2').split())
PROTECTED_NAMES={'all_users','backup','db_storage','config','cache','temp','tmp','resource','business','apm_record','mmkv','logs','log','favorite','emoticon','sns','xweb','xeditor','thumb','thumbs','.thumbnails','msgattach','attach'}

def describe_directory(path,account,alias=''):
    p=Path(canonical(path));root=Path(canonical(account))
    try:parts=tuple(x.lower() for x in p.relative_to(root).parts)
    except ValueError:return dict(name=alias or p.name,original=p.name,path=str(p),known=False,kind='unknown',description='不属于当前账号目录，用途尚未确认。')
    if not parts:return dict(name=alias or root.name,original=root.name,path=str(p),known=True,kind='account',description='微信账号的本地存储根目录；账号中文名称仅在本软件内生效。')
    rule=RULES.get(parts)
    # Known storage descendants keep their role, but retain their actual label.
    prefix=next((key for key in sorted(RULES,key=len,reverse=True) if parts[:len(key)]==key),None)
    if rule is None and prefix and RULES[prefix][2]!='mixed':
        title,explanation,kind=RULES[prefix]
        label=p.name
        if len(label)==7 and label[4]=='-' and label[:4].isdigit() and label[5:].isdigit():label=label[:4]+'年'+label[5:]+'月'
        return dict(name=alias or label,original=p.name,path=str(p),known=True,kind=kind,description=f'{title}下的子目录。'+explanation)
    if rule:
        title,explanation,kind=rule
        return dict(name=alias or title,original=p.name,path=str(p),known=True,kind=kind,description=explanation)
    return dict(name=alias or p.name,original=p.name,path=str(p),known=False,kind='unknown',description='用途尚未确认。保留原始名称，可添加别名和备注；不允许通过本软件删除其中的文件。')

def deletion_path_allowed(path,account):
    p=Path(canonical(path));root=Path(canonical(account))
    try:parts=tuple(x.lower() for x in p.relative_to(root).parts)
    except ValueError:return False
    if len(parts)<3 or any(x in PROTECTED_NAMES for x in parts[:-1]):return False
    if not any(parts[:len(prefix)]==prefix for prefix in DELETE_PREFIXES):return False
    return p.suffix.lower() in DELETE_EXTENSIONS

def virtual_sections(account):
    root=Path(account)
    candidates=[('聊天数据库（只读）',['db_storage']),('聊天文件 / 文档',['msg/file','FileStorage/File']),('图片与附件资源',['FileStorage/Image','msg/attach']),('聊天视频',['msg/video','FileStorage/Video']),('缓存与临时数据（只读）',['cache','temp']),('其他数据 / 全部原始目录',[])]
    return [(name,[str(root/p) for p in paths if (root/p).is_dir()]) for name,paths in candidates]
