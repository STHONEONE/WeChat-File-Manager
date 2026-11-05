from zipfile import ZipFile

from PySide6.QtGui import QColor,QImage
from app.office_preview import office_preview


def test_office_preview_uses_document_and_presentation_order(tmp_path):
    word = tmp_path / 'example.docx'
    with ZipFile(word, 'w') as package:
        package.writestr('word/document.xml', '<document><p><t>首页标题</t></p></document>')
    assert '首页标题' in office_preview(word)

    slides = tmp_path / 'example.pptx'
    with ZipFile(slides, 'w') as package:
        package.writestr('ppt/presentation.xml', '<presentation xmlns:r="urn:r"><sldId r:id="rId2"/></presentation>')
        package.writestr('ppt/_rels/presentation.xml.rels', '<Relationships><Relationship Id="rId2" Target="slides/slide2.xml"/></Relationships>')
        package.writestr('ppt/slides/slide1.xml', '<slide><p><t>旧封面</t></p></slide>')
        package.writestr('ppt/slides/slide2.xml', '<slide><p><t>新封面</t></p></slide>')
    assert '新封面' in office_preview(slides)
    assert '旧封面' not in office_preview(slides)


def test_excel_preview_reads_first_sheet_and_shared_strings(tmp_path):
    excel = tmp_path / 'example.xlsx'
    with ZipFile(excel, 'w') as package:
        package.writestr('xl/workbook.xml', '<workbook xmlns:r="urn:r"><sheet name="汇总" r:id="rId1"/></workbook>')
        package.writestr('xl/_rels/workbook.xml.rels', '<Relationships><Relationship Id="rId1" Target="/xl/worksheets/sheet2.xml"/></Relationships>')
        package.writestr('xl/worksheets/sheet2.xml', '<worksheet><row><c t="s"><v>0</v></c><c><v>12</v></c></row></worksheet>')
        package.writestr('xl/sharedStrings.xml', '<sst><si><t>数量</t></si></sst>')
    assert '「汇总」' in office_preview(excel)
    assert '数量  |  12' in office_preview(excel)


def test_saved_cover_is_shown_even_without_document_text(tmp_path):
    cover = tmp_path / 'cover.png'
    image = QImage(24,16,QImage.Format.Format_RGB32)
    image.fill(QColor('blue'))
    assert image.save(str(cover))
    document = tmp_path / 'with-cover.docx'
    with ZipFile(document,'w') as package:
        package.write(cover,'docProps/thumbnail.png')
    preview = office_preview(document)
    assert isinstance(preview,QImage) and not preview.isNull()
