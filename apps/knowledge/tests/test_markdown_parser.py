"""Markdown parser tests."""

from io import BytesIO


def parse_markdown(source: str, filename="guide.md"):
    from apps.knowledge.parsers import parse_document

    return parse_document(BytesIO(source.encode("utf-8")), filename)


def test_markdown_parser_tracks_heading_hierarchy_and_segment_boundaries():
    segments = parse_markdown(
        """# 部署
部署概览。

## PostgreSQL 配置
数据库配置正文。

### 备份
备份正文。

## 应用配置
应用正文。
"""
    )

    assert [segment.section_title for segment in segments] == [
        "部署",
        "部署 > PostgreSQL 配置",
        "部署 > PostgreSQL 配置 > 备份",
        "部署 > 应用配置",
    ]
    assert [segment.content for segment in segments] == [
        "部署概览。",
        "数据库配置正文。",
        "备份正文。",
        "应用正文。",
    ]
    assert segments[1].source_reference == "《guide.md》 > 部署 > PostgreSQL 配置"
    assert segments[1].metadata == {
        "file_type": "markdown",
        "section_path": ["部署", "PostgreSQL 配置"],
    }


def test_markdown_parser_keeps_list_quote_and_code_block_text_searchable():
    segments = parse_markdown(
        """# 运维
- 检查数据库
- 检查应用

> 先备份再升级

```bash
pg_ctl status
```
"""
    )

    content = segments[0].content
    assert "检查数据库" in content
    assert "检查应用" in content
    assert "先备份再升级" in content
    assert "pg_ctl status" in content
    assert "```" not in content
    assert "> " not in content


def test_markdown_parser_does_not_render_or_include_html_markup():
    segments = parse_markdown(
        """# 安全
<span>可检索文本</span>

<script>external_call()</script>
"""
    )

    content = segments[0].content
    assert "可检索文本" in content
    assert "<span>" not in content
    assert "<script>" not in content
    assert "external_call" not in content


def test_markdown_parser_keeps_link_text_without_loading_external_resource():
    segments = parse_markdown(
        "# 参考\n查看 [产品资料](https://unreachable.invalid/product.pdf)。"
    )

    assert segments[0].content == "查看 产品资料。"
    assert "https://" not in segments[0].content


def test_markdown_parser_returns_preamble_without_a_section():
    segments = parse_markdown("文档前言。\n\n# 第一章\n章节正文。")

    assert segments[0].content == "文档前言。"
    assert segments[0].section_title is None
    assert segments[0].source_reference == "《guide.md》"
