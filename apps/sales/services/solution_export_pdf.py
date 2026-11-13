"""CJK PDF rendering without runtime downloads or external resource loading."""
import hashlib
import json
from pathlib import Path
from threading import Lock
from xml.sax.saxutils import escape

from apps.sales.services.solution_export_guard import SolutionExportError
from apps.sales.services.solution_export_rendering import BoundedBytesIO

FONT_DIR = Path(__file__).resolve().parents[1] / 'assets/fonts'
_FONT_LOCK = Lock()


def _font():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    try:
        manifest = json.loads((FONT_DIR/'manifest.json').read_text(encoding='utf-8'))
        data = (FONT_DIR/'NotoSansSC-Regular.ttf').read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != manifest['static_sha256']:
            raise ValueError()
        name = 'SalesMindSC-' + digest[:12]
        with _FONT_LOCK:
            try:
                font = pdfmetrics.getFont(name)
            except KeyError:
                font = TTFont(name,str(FONT_DIR/'NotoSansSC-Regular.ttf'))
                pdfmetrics.registerFont(font)
        return name,font.face.charToGlyph
    except Exception:
        raise SolutionExportError('solution_export_unavailable') from None


def render_pdf(document) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    name,glyphs = _font()
    normal = ParagraphStyle('body',fontName=name,fontSize=11,leading=16,spaceAfter=6,wordWrap='CJK',splitLongWords=True)
    heading = ParagraphStyle('heading',parent=normal,fontSize=16,leading=22,spaceBefore=14,spaceAfter=9,keepWithNext=True)
    subheading = ParagraphStyle('subheading',parent=normal,spaceBefore=7,spaceAfter=5,keepWithNext=True)
    title_style = ParagraphStyle('title',parent=heading,fontSize=23,leading=30,spaceBefore=0)

    def paragraph(text,style=normal):
        if any(ord(c) not in glyphs and c not in '\n\r\t' for c in text):
            # The bundled font cannot draw this content: a payload defect, not
            # a service outage.
            raise SolutionExportError('solution_export_invalid_payload')
        return Paragraph(escape(text).replace('\n','<br/>'),style)

    story = [paragraph(document.title,title_style)]
    story += [paragraph(f'{k}：{v}') for k,v in document.metadata]
    story += [Spacer(1,8),paragraph(document.disclaimer)]
    for part in document.sections:
        story.append(paragraph(part.title,heading))
        for block in part.blocks:
            if block.kind == 'table' and block.rows:
                table = Table([[paragraph(cell) for cell in row] for row in block.rows],
                    colWidths=[(A4[0]-40*mm)/len(block.rows[0])]*len(block.rows[0]),repeatRows=1,
                    splitByRow=1,splitInRow=1)
                table.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.5,'#D9D9D9'),
                    ('BACKGROUND',(0,0),(-1,0),'#E8EEF4'),('VALIGN',(0,0),(-1,-1),'MIDDLE'),
                    ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
                story.append(table)
            else:
                story.append(paragraph(block.text,subheading if block.kind=='heading' else normal))
    story.append(paragraph('来源索引',heading))
    for source in document.source_index:
        story += [paragraph(f'[{source.label}] 文档 #{source.document_id}' + (f'：{source.title}' if source.title else '')),
            paragraph('声明／陈述：' + ', '.join(source.statement_ids))]
    version = next(v for k,v in document.metadata if k == '方案版本')

    def page(canvas,doc):
        canvas.saveState()
        canvas.setFont(name,9)
        canvas.drawString(20*mm,A4[1]-12*mm,f'SalesMind AI / {version}')
        canvas.drawRightString(A4[0]-20*mm,12*mm,str(doc.page))
        canvas.restoreState()

    with BoundedBytesIO() as output:
        SimpleDocTemplate(output,pagesize=A4,leftMargin=20*mm,rightMargin=20*mm,
            topMargin=20*mm,bottomMargin=20*mm,title=document.title,author='SalesMind AI').build(
                story,onFirstPage=page,onLaterPages=page)
        return output.getvalue()
