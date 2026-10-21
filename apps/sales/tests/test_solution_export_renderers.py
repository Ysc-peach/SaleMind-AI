"""Actual file contents and bounded rendering, including hostile plain text."""
from dataclasses import replace
from io import BytesIO
from zipfile import ZipFile

import pytest
from pypdf import PdfReader
from apps.sales.tests.test_solution_export_document import snapshot


def document():
    from apps.sales.services.solution_export_document import build_export_document
    return build_export_document(snapshot())


def test_docx_is_real_a4_document_with_complete_content_and_page_fields():
    from docx import Document
    from apps.sales.services.solution_export_docx import render_docx
    content = render_docx(document())
    restored = Document(BytesIO(content))
    assert round(restored.sections[0].page_width.mm) == 210
    assert round(restored.sections[0].page_height.mm) == 297
    text = '\n'.join(p.text for p in restored.paragraphs)
    assert '客户需要企业知识查询。' in text
    assert '范围边界' in text
    with ZipFile(BytesIO(content)) as archive:
        assert b'PAGE' in archive.read('word/footer1.xml')
        assert not any('vbaProject' in n for n in archive.namelist())


def test_pdf_embeds_cjk_font_and_preserves_text():
    from apps.sales.services.solution_export_pdf import render_pdf
    content = render_pdf(document())
    reader = PdfReader(BytesIO(content))
    text = ''.join(p.extract_text() for p in reader.pages)
    assert '客户需要企业知识查询。' in text
    assert '范围边界' in text and '企业能力' in text
    assert b'/FontFile2' in content


def test_special_characters_are_plain_text_not_markup():
    from apps.sales.services.solution_export_pdf import render_pdf
    from apps.sales.services.solution_export_docx import render_docx
    doc = replace(document(), title='<b>方案 & "说明"</b>')
    text = ''.join(p.extract_text() for p in PdfReader(BytesIO(render_pdf(doc))).pages)
    assert '<b>方案 & "说明"</b>' in text
    with ZipFile(BytesIO(render_docx(doc))) as archive:
        assert b'TargetMode="External"' not in archive.read('word/_rels/document.xml.rels')


def test_font_missing_or_unsupported_glyph_fails_safely(monkeypatch, tmp_path):
    from apps.sales.services import solution_export_pdf
    from apps.sales.services.solution_export_guard import SolutionExportError
    monkeypatch.setattr(solution_export_pdf, 'FONT_DIR', tmp_path)
    with pytest.raises(SolutionExportError) as caught:
        solution_export_pdf.render_pdf(document())
    assert caught.value.status == 503


def test_unsupported_glyph_is_not_silently_replaced():
    from apps.sales.services.solution_export_pdf import render_pdf
    from apps.sales.services.solution_export_guard import SolutionExportError
    with pytest.raises(SolutionExportError):
        render_pdf(replace(document(),title='方案\U0001f9ff'))


def test_exact_size_boundary_and_growth_after_seek():
    from apps.sales.services.solution_export_rendering import BoundedBytesIO
    from apps.sales.services.solution_export_guard import SolutionExportError
    buf = BoundedBytesIO(limit=5)
    buf.write(b'12345')
    assert buf.getvalue() == b'12345'
    with pytest.raises(SolutionExportError) as caught:
        buf.write(b'6')
    assert caught.value.code == 'solution_export_too_large'
    buf.seek(4)
    with pytest.raises(SolutionExportError):
        buf.write(b'67')


def test_many_pages_keep_final_source_and_long_table_cell():
    from apps.sales.services.solution_export_document import DocumentBlock, DocumentSection
    from apps.sales.services.solution_export_pdf import render_pdf
    text = '完整中文内容 ' * 1400 + 'END_SENTINEL'
    doc = replace(document(),sections=(DocumentSection('长表格',(
        DocumentBlock('table',rows=(('编号','内容'),('1',text))),)),))
    reader = PdfReader(BytesIO(render_pdf(doc)))
    assert len(reader.pages) > 2
    extracted = ''.join(p.extract_text() for p in reader.pages)
    assert 'END_SENTINEL' in extracted and '企业能力' in extracted


def test_component_phase_and_claim_labels_are_kept_with_following_body():
    from docx import Document
    from apps.sales.services.solution_export_docx import render_docx
    doc = Document(BytesIO(render_docx(document())))
    labels = [p for p in doc.paragraphs if p.text in {'职责','接口','设计理由','目标','任务','交付物'}]
    assert labels
    assert all(p.paragraph_format.keep_with_next or p.style.paragraph_format.keep_with_next for p in labels)


def test_title_has_no_inherited_horizontal_rule():
    from docx import Document
    from docx.oxml.ns import qn
    from apps.sales.services.solution_export_docx import render_docx
    doc = Document(BytesIO(render_docx(document())))
    assert not doc.styles['Title']._element.findall('.//'+qn('w:pBdr'))
