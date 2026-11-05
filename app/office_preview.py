"""Read a small preview from Office packages without launching Office."""
import posixpath
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from PySide6.QtCore import QBuffer,QIODevice,QSize,Qt
from PySide6.QtGui import QImageReader

OFFICE_PREVIEW_EXTENSIONS = {'.docx', '.docm', '.xlsx', '.xlsm', '.pptx', '.pptm'}


def xml(package, name, limit=4 * 1024**2):
    info = package.getinfo(name)
    if info.file_size > limit:
        raise ValueError('文档预览数据过大')
    with package.open(info) as stream:
        data = stream.read(limit + 1)
    if len(data) > limit or b'<!DOCTYPE' in data.replace(b'\0',b'').upper():
        raise ValueError('文档预览数据不受支持')
    return ET.fromstring(data)


def first_part(package, main, tag):
    item = xml(package, main).find('.//{*}' + tag)
    if item is None:
        return None, ''
    rid = next((value for key, value in item.attrib.items() if key.endswith('}id')), None)
    directory, filename = posixpath.split(main)
    relations = xml(package, posixpath.join(directory, '_rels', filename + '.rels'))
    for rel in relations:
        if rel.get('Id') == rid and rel.get('TargetMode') != 'External':
            target = rel.get('Target', '')
            path = target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join(directory, target))
            if path.startswith(directory + '/'):
                return path, item.get('name', '')
    return None, ''


def paragraphs(root):
    lines = []
    for paragraph in root.iterfind('.//{*}p'):
        line = ''.join(node.text or '' for node in paragraph.iterfind('.//{*}t')).strip()
        if line:
            lines.append(line[:240])
            if len(lines) == 14:
                break
    return lines


def sheet_preview(package):
    path, name = first_part(package, 'xl/workbook.xml', 'sheet')
    if not path:
        return None
    sheet = xml(package, path)
    strings = []
    if 'xl/sharedStrings.xml' in package.namelist():
        try:
            strings = [''.join(node.text or '' for node in entry.iterfind('.//{*}t'))
                       for entry in xml(package, 'xl/sharedStrings.xml')]
        except ValueError:
            pass
    lines = []
    for row in sheet.iterfind('.//{*}row'):
        cells = []
        for cell in list(row)[:6]:
            value = cell.findtext('{*}v', '')
            if cell.get('t') == 's' and value.isdecimal():
                index = int(value)
                value = strings[index] if index < len(strings) else ''
            elif cell.get('t') == 'inlineStr':
                value = ''.join(node.text or '' for node in cell.iterfind('.//{*}t'))
            cells.append(value[:40])
        if any(cells):
            lines.append('  |  '.join(cells))
            if len(lines) == 10:
                break
    return 'Excel · 首张表' + (f'「{name}」' if name else '') + '\n\n' + '\n'.join(lines) if lines else None


def office_preview(path):
    suffix = Path(path).suffix.lower()
    with ZipFile(path) as package:
        for info in package.infolist():
            if info.filename.lower() not in {
                'docprops/thumbnail.jpeg', 'docprops/thumbnail.jpg', 'docprops/thumbnail.png',
                'docprops/thumbnail.emf', 'docprops/thumbnail.wmf',
            } or info.file_size > 512 * 1024:
                continue
            buffer = QBuffer()
            buffer.setData(package.read(info))
            buffer.open(QIODevice.OpenModeFlag.ReadOnly)
            reader = QImageReader(buffer)
            dimensions = reader.size()
            if not dimensions.isValid() or dimensions.width()*dimensions.height()>8_000_000:
                continue
            dimensions.scale(QSize(520,650),Qt.AspectRatioMode.KeepAspectRatio)
            reader.setScaledSize(dimensions)
            image = reader.read()
            if not image.isNull():
                return image
        if suffix in {'.xlsx', '.xlsm'}:
            return sheet_preview(package)
        if suffix in {'.docx', '.docm'}:
            part, label = 'word/document.xml', 'Word · 文档开头'
        else:
            part, _ = first_part(package, 'ppt/presentation.xml', 'sldId')
            label = 'PPT · 第一张幻灯片文字'
        lines = paragraphs(xml(package, part)) if part else []
        return label + '\n\n' + '\n'.join(lines) if lines else None
