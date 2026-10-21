"""Version adapters to immutable, plaintext document content (no database I/O)."""
from dataclasses import dataclass

from apps.sales.services.solution_export_guard import ExportSnapshot, SolutionExportError
from apps.sales.services.solution_schema import SolutionDraft

DISCLAIMER = '本文件为导出时有效的内部技术审核版本，可用于技术沟通；不构成报价、合同、客户验收、性能或 SLA 承诺。导出后的编辑内容不自动继承系统审核。'
_TYPES = {'customer_fact':'客户事实','enterprise_fact':'企业事实','proposal':'建议','assumption':'假设','unresolved':'待确认'}


@dataclass(frozen=True, slots=True)
class DocumentBlock:
    kind: str
    text: str = ''
    rows: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True, slots=True)
class DocumentSection:
    title: str
    blocks: tuple[DocumentBlock, ...]


@dataclass(frozen=True, slots=True)
class ExportSource:
    label: str
    document_id: int
    title: str
    statement_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExportDocument:
    title: str
    metadata: tuple[tuple[str,str], ...]
    disclaimer: str
    sections: tuple[DocumentSection, ...]
    source_index: tuple[ExportSource, ...]


def build_export_document(snapshot: ExportSnapshot) -> ExportDocument:
    metadata = tuple((name,str(value)) for name,value in (
        ('方案 ID',snapshot.solution_id),('方案版本',f'V{snapshot.version}'),
        ('Schema',snapshot.schema_version),('分析快照',snapshot.analysis_id),
        ('创建人 ID',snapshot.created_by_id),('创建时间',snapshot.created_at.isoformat()),
        ('批准记录 ID',snapshot.approval_id),('审核人 ID',snapshot.reviewer_id),
        ('通过时间',snapshot.approved_at.isoformat()),('导出时间',snapshot.exported_at.isoformat()),
    ))
    grouped = {}
    for source in snapshot.sources:
        key = (source.citation_label,source.document_id,source.document_title if snapshot.schema_version==2 else '')
        grouped.setdefault(key,set()).add(source.claim_id or source.statement_path)
    sources = tuple(ExportSource(label,doc_id,title,tuple(sorted(ids)))
        for (label,doc_id,title),ids in sorted(grouped.items()))
    sections = _v1(snapshot.domain) if isinstance(snapshot.domain,SolutionDraft) else _v2(snapshot.domain)
    return ExportDocument(snapshot.title,metadata,DISCLAIMER,sections,sources)


def _paragraph(text):
    return DocumentBlock('paragraph',text)


def _heading(text):
    return DocumentBlock('heading',text)


def _v1(draft):
    def statement(item,path):
        return _paragraph(f'{path} [{_TYPES[item.type.value]}] {item.text}' +
            (f' [{", ".join(item.citations)}]' if item.citations else ''))
    sections = [DocumentSection('执行摘要',tuple(statement(s,f'executive_summary[{i}]')
        for i,s in enumerate(draft.executive_summary)))]
    for section in draft.solution_sections:
        sections.append(DocumentSection(section.title,tuple(statement(s,
            f'solution_sections.{section.key}.statements[{i}]') for i,s in enumerate(section.statements))))
    sections.append(DocumentSection('假设',tuple(_paragraph(f'{a.text}（关联需求：{", ".join(a.related_fields)}）')
        for a in draft.assumptions)))
    return tuple(sections)


def _v2(draft):
    claims = {c.claim_id:c for c in draft.claims}
    seen = set()

    def statements(ids, label=None):
        blocks = [_heading(label)] if label and ids else []
        for claim_id in ids:
            if claim_id not in claims:
                raise SolutionExportError('solution_export_invalid_payload')
            c = claims[claim_id]
            seen.add(claim_id)
            text = f'{c.claim_id} [{_TYPES[c.statement_type.value]}] {c.text}'
            if c.citations:
                text += f' [{", ".join(c.citations)}]'
            if c.related_requirement_fields:
                text += f'（关联需求：{", ".join(c.related_requirement_fields)}）'
            blocks.append(_paragraph(text))
        return blocks

    def info(label,values):
        return _paragraph(f'{label}：{", ".join(str(v) for v in values) or "无"}')

    groups = [[] for _ in range(12)]
    groups[0] += statements(draft.executive_summary_claim_ids)
    groups[1] += statements(draft.customer_context.confirmed_claim_ids,'已确认客户事实')
    groups[1] += statements(draft.customer_context.unresolved_claim_ids,'未确认事项')
    for ref in draft.customer_context.requirement_fields:
        groups[1] += statements(ref.claim_ids,f'需求字段：{ref.field} / {ref.status}')
    groups[2] += statements(draft.proposed_solution.overview_claim_ids)
    for group in draft.proposed_solution.capability_groups:
        groups[2] += statements(group.claim_ids,f'{group.title} ({group.group_id})')
    groups[3] += statements(draft.architecture.overview_claim_ids)
    component_ids = {c.component_id for c in draft.architecture.components}
    for c in draft.architecture.components:
        if not set(c.dependency_component_ids) <= component_ids:
            raise SolutionExportError('solution_export_invalid_payload')
        groups[3].append(_heading(f'{c.name} ({c.component_id})'))
        if c.identity_claim_id:
            groups[3] += statements((c.identity_claim_id,),'组件身份')
        groups[3] += statements(c.responsibility_claim_ids,'职责')
        groups[3] += statements(c.rationale_claim_ids,'设计理由')
        groups[3] += statements(c.interface_claim_ids,'接口')
        groups[3].append(info('依赖组件',c.dependency_component_ids))
    for flow in draft.architecture.flows:
        if flow.source_component_id not in component_ids or flow.target_component_id not in component_ids:
            raise SolutionExportError('solution_export_invalid_payload')
        groups[3].append(_paragraph(f'{flow.flow_type}：{flow.source_component_id} -> {flow.target_component_id}'))
    for block in draft.deployment_and_integration:
        groups[4] += statements(block.claim_ids,f'{block.title} ({block.block_id} / {block.topic})')
    phase_ids = {p.phase_id for p in draft.implementation_plan.phases}
    criterion_ids = {c.criterion_id for c in draft.acceptance_criteria}
    for p in draft.implementation_plan.phases:
        if not set(p.dependency_phase_ids) <= phase_ids or not set(p.acceptance_criterion_ids) <= criterion_ids:
            raise SolutionExportError('solution_export_invalid_payload')
        groups[5].append(_heading(f'{p.name} ({p.phase_id})'))
        for label,ids in [('目标',p.objective_claim_ids),('任务',p.task_claim_ids),('交付物',p.deliverable_claim_ids)]:
            groups[5] += statements(ids,label)
        groups[5] += [info('责任角色',p.owner_roles),info('依赖阶段',p.dependency_phase_ids),info('验收关系',p.acceptance_criterion_ids)]
        if p.timing_claim_id:
            groups[5] += statements((p.timing_claim_id,),f'时间分类：{p.timing_classification}')
    for risk in draft.risks:
        groups[6].append(_heading(risk.risk_id))
        for label,ids in [('条件',(risk.condition_claim_id,)),('影响',risk.impact_claim_ids),('缓解',risk.mitigation_claim_ids),('触发',risk.trigger_claim_ids)]:
            groups[6] += statements(ids,label)
    for c in draft.acceptance_criteria:
        groups[7] += statements((c.claim_id,),f'{c.criterion_id} / {c.classification}')
    for m in draft.milestones:
        if not set(m.related_phase_ids) <= phase_ids:
            raise SolutionExportError('solution_export_invalid_payload')
        groups[8].append(_heading(f'{m.name} ({m.milestone_id})'))
        groups[8].append(info('关联阶段',m.related_phase_ids))
        groups[8] += statements(m.outcome_claim_ids,'预期结果')
        if m.timing_claim_id:
            groups[8] += statements((m.timing_claim_id,),f'时间分类：{m.timing_classification}')
    groups[9] += statements(draft.assumption_claim_ids)
    for q in draft.open_questions:
        groups[10] += statements((q.unresolved_claim_id,),f'{q.question_id} / {q.requirement_field} / {q.requirement_status}')
    for scope in draft.out_of_scope:
        groups[11] += statements((scope.claim_id,),f'{scope.scope_id} / {scope.classification}')
    # A saved registry entry must not disappear merely because no container references it.
    for claim in draft.claims:
        if claim.claim_id not in seen:
            destination = {'customer_fact':1,'enterprise_fact':2,'proposal':2,'assumption':9,'unresolved':10}[claim.statement_type.value]
            groups[destination] += statements((claim.claim_id,))
    titles = ['执行摘要','客户背景','总体方案','系统架构','部署与集成','实施计划','风险','验收标准','里程碑','假设','待确认事项','范围边界']
    return tuple(DocumentSection(title,tuple(blocks)) for title,blocks in zip(titles,groups))
