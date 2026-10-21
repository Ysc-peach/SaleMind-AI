"""Real, macro-free DOCX from the shared plaintext document projection."""
from apps.sales.services.solution_export_rendering import BoundedBytesIO


def render_docx(document) -> bytes:
    from docx import Document
    from docx.shared import Mm, Pt, RGBColor
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    doc = Document()
    doc.core_properties.author = 'SalesMind AI'
    doc.core_properties.title = document.title
    doc.core_properties.comments = ''
    section = doc.sections[0]
    section.page_width,section.page_height = Mm(210),Mm(297)
    section.top_margin = section.bottom_margin = section.left_margin = section.right_margin = Mm(20)
    for name in ['Normal','Title','Heading 1','Heading 2','List Bullet']:
        style = doc.styles[name]
        style.font.name = 'Noto Sans SC'
        style.font.color.rgb = RGBColor(0,0,0)
        style._element.get_or_add_rPr().get_or_add_rFonts().set(qn('w:eastAsia'),'Noto Sans SC')
    doc.styles['Normal'].font.size = Pt(11)
    for border in doc.styles['Title']._element.findall('.//'+qn('w:pBdr')):
        border.getparent().remove(border)
    doc.styles['Normal'].paragraph_format.space_after = Pt(6)
    doc.styles['Normal'].paragraph_format.line_spacing = 1.25
    version = next(v for k,v in document.metadata if k == '方案版本')
    section.header.paragraphs[0].text = f'SalesMind AI · {version}'
    page = OxmlElement('w:fldSimple')
    page.set(qn('w:instr'),'PAGE')
    section.footer.paragraphs[0]._p.append(page)
    doc.add_heading(document.title,0)
    for label,value in document.metadata:
        doc.add_paragraph(f'{label}：{value}')
    doc.add_paragraph(document.disclaimer)
    for part in document.sections:
        doc.add_heading(part.title,1)
        for block in part.blocks:
            if block.kind == 'table' and block.rows:
                table = doc.add_table(rows=0,cols=len(block.rows[0]))
                table.style = 'Table Grid'
                for values in block.rows:
                    for cell,text in zip(table.add_row().cells,values):
                        cell.text = text
                header = OxmlElement('w:tblHeader')
                table.rows[0]._tr.get_or_add_trPr().append(header)
            else:
                style = {'list':'List Bullet','heading':'Heading 2'}.get(block.kind)
                doc.add_paragraph(block.text,style=style)
    doc.add_heading('来源索引',1)
    for source in document.source_index:
        doc.add_paragraph(f'[{source.label}] 文档 #{source.document_id}' + (f'：{source.title}' if source.title else ''))
        doc.add_paragraph('声明／陈述：' + ', '.join(source.statement_ids))
    with BoundedBytesIO() as output:
        doc.save(output)
        return output.getvalue()
