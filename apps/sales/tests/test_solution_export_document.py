"""Export adapters preserve identities and structure, not private input data."""
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from apps.sales.tests.test_solution_schema_v2 import valid_draft
from apps.sales.tests.solution_fakes import solution_payload
from apps.sales.services.solution_payloads import deserialize_solution_payload


def snapshot(domain=None):
    now = datetime(2026, 10, 14, tzinfo=timezone.utc)
    return SimpleNamespace(domain=domain or valid_draft(), title='企业技术方案',
        solution_id=151, version=2, schema_version=2, analysis_id=298,
        created_by_id=2, created_at=now, approval_id=94, reviewer_id=3,
        approved_at=now, exported_at=now,
        sources=(SimpleNamespace(citation_label='S1', document_id=10, document_title='企业能力',
            statement_path='claims.C0002', claim_id='C0002', source_excerpt='PRIVATE_EXCERPT'),
            SimpleNamespace(citation_label='S1', document_id=10, document_title='企业能力',
            statement_path='claims.C0003', claim_id='C0003', source_excerpt='PRIVATE_EXCERPT')),
        raw_requirement='PRIVATE_RAW', comment='PRIVATE_COMMENT')


def test_v2_projection_has_all_sections_and_relationships():
    from apps.sales.services.solution_export_document import build_export_document
    document = build_export_document(snapshot())
    assert [s.title for s in document.sections] == ['执行摘要','客户背景','总体方案','系统架构',
        '部署与集成','实施计划','风险','验收标准','里程碑','假设','待确认事项','范围边界']
    text = repr(document)
    for item in valid_draft().claims:
        assert item.text in text
        assert item.claim_id in text
    for marker in ['knowledge_service', 'phase_discovery', 'AC01', 'joint', 'unresolved', 'proposed']:
        assert marker in text
    assert '不构成报价、合同、客户验收、性能或 SLA 承诺' in document.disclaimer
    assert all(s.statement_ids for s in document.source_index)


def test_projection_omits_private_excerpt_raw_requirement_and_review_comment():
    from apps.sales.services.solution_export_document import build_export_document
    text = repr(build_export_document(snapshot()))
    for secret in ['PRIVATE_EXCERPT','PRIVATE_RAW','PRIVATE_COMMENT']:
        assert secret not in text


def test_v1_projection_preserves_five_sections_and_summary_aliases():
    from apps.sales.services.solution_export_document import build_export_document
    domain = deserialize_solution_payload(1, solution_payload())
    snap = snapshot(domain)
    snap.schema_version = 1
    document = build_export_document(snap)
    assert [s.title for s in document.sections] == ['执行摘要','总体方案','部署方案','数据安全','系统集成','实施建议','假设']
    assert 'executive_summary[0]' in repr(document)
    assert 'solution_sections.overall_approach.statements[0]' in repr(document)
    assert '企业资料确认支持私有化部署。' in repr(document)


def test_equal_text_claims_keep_distinct_identity_and_sources():
    from apps.sales.services.solution_export_document import build_export_document
    draft = valid_draft()
    twin = replace(draft.claims[2], text=draft.claims[1].text)
    snap = snapshot(replace(draft, claims=(*draft.claims[:2],twin,*draft.claims[3:])))
    text = repr(build_export_document(snap))
    assert 'C0002' in text and 'C0003' in text
    assert text.count(draft.claims[1].text) >= 2


def test_projection_fails_on_missing_referenced_object():
    from apps.sales.services.solution_export_document import build_export_document
    from apps.sales.services.solution_export_guard import SolutionExportError
    draft = valid_draft()
    with pytest.raises(SolutionExportError):
        build_export_document(snapshot(replace(draft, executive_summary_claim_ids=('MISSING',))))


def test_empty_unresolved_group_does_not_label_known_requirements_as_unknown():
    from apps.sales.services.solution_export_document import build_export_document
    draft=valid_draft()
    context=replace(draft.customer_context,unresolved_claim_ids=(),
        requirement_fields=draft.customer_context.requirement_fields[:1])
    document=build_export_document(snapshot(replace(draft,customer_context=context)))
    text='\n'.join(b.text for b in document.sections[1].blocks)
    assert 'business_goal / known' in text
    assert '未确认事项' not in text
    architecture='\n'.join(b.text for b in document.sections[3].blocks)
    assert '\n接口\n' not in '\n'+architecture+'\n'
