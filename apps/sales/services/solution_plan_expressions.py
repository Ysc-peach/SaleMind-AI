"""Bounded full-consumption planning grammar. Its clauses are never admission."""

from dataclasses import dataclass
from enum import StrEnum
import re

from .solution_clarification_actions import (
    clarification_object_sequence, clear_clarification_action, scoped_statements,
    _ENVIRONMENT_NAME,
)


class PlanClauseKind(StrEnum):
    INQUIRY = "inquiry"
    CONDITIONAL_WORK = "conditional_work"
    PLANNED_ARTIFACT = "planned_artifact"
    HYPOTHETICAL_RISK = "hypothetical_risk"
    VERIFICATION_OUTCOME = "verification_outcome"
    ASSERTION = "assertion"


class PlanPrerequisite(StrEnum):
    NONE = "none"
    COMPLETED = "completed"
    SATISFIED = "satisfied"


@dataclass(frozen=True)
class PlanClause:
    kind: PlanClauseKind
    prerequisite: PlanPrerequisite = PlanPrerequisite.NONE
    dependencies: tuple[str, ...] = ()


_VERBS = r"核对|核验|验证|评估|确认|测量|检查|测试|收集|统计"
_STAGE = r"(?:准备|建设|实施|部署|上线|验收|联调|试点)(?:阶段)?(?:前|期间)"
_PREFIX = re.compile(r"^(?:并且|同时|然后|并|再)?(?:建议|计划|拟|应|需|需要)?(?:在)?(?:" + _STAGE + r")?(?:先|优先)?")
_INQUIRY = re.compile(r"^(?:" + _VERBS + r")(.+?)$")
_QUESTION = re.compile(r"(?:是否|能否)(?:满足(?:本期)?(?:平台|试点范围)?的?(?:部署)?需求|符合部署条件|足够|可用)\Z")
_BACKGROUND = re.compile(
    r"(?:现有|当前|目标|沿用)\s*(?:" + _ENVIRONMENT_NAME + r"\s*)?(?:运行)?环境"
    r"(?:\s*[、和与及]\s*" + _ENVIRONMENT_NAME + r"(?:\s*配置)?)+"
    r"对本期部署的承载条件\Z"
)
_ASSESSMENT = r"(?:环境|容量|资源|部署条件)(?:[与和及、](?:环境|容量|资源|部署条件))*"
_ARTIFACT = re.compile(r"(?:形成|记录)?(?:" + _ASSESSMENT + r")?(?:核对|核验|验证|评估|检查|测试|测量|统计)(?:结果|记录|报告)(?:，?记录是否满足及差距)?\Z")
_OUTCOME = re.compile(r"完成(?:" + _ASSESSMENT + r")?(?:核验|核对|评估|检查|测试)(?:并(?:记录(?:结果(?:和后续处理意见)?|差距)|确认(?:本期)?部署条件))\Z")
# Technical targets are closed nouns, not arbitrary text or approved capabilities.
# Only a complete future action under a parsed prerequisite can use this form.
_WORK_TARGET = r"(?:检索入口|上传索引|检索服务)"
_WORK_TARGETS = _WORK_TARGET + r"(?:[、和与及]" + _WORK_TARGET + r"){0,2}"
_TECHNICAL_WORK = (
    r"(?:按已验证方案)?(?:完成" + _WORK_TARGETS + r"的(?:落地)?接入|接入" + _WORK_TARGETS + r")"
)
_WORK = re.compile(
    r"(?:再|才|再安排)?(?:开展建设|建设|上线|安排上线|安排部署|开展部署|实施部署|部署|"
    r"启动试点|开展试点|排期|排定本阶段时间|配置\d+台服务器|" + _TECHNICAL_WORK + r")\Z"
)
_SATISFIED = re.compile(r"(?:若|在)?(?:经)?(?:核验|核对|验证)(?:确认)?(.+?)满足(?:部署条件|需求)?(?:后|[，,]?则)[，,]?\s*(.+)\Z")
_COMPLETED = re.compile(r"(?:在)?(?:(?:" + _ASSESSMENT + r")?(?:核验|核对|验证|确认))完成后[，,]?\s*(.+)\Z")
_PENDING_INQUIRY = re.compile(r"(?:若客户(?:同意|提供资源)|待客户确认(?:部署条件|服务器容量足够)后)[，,]?(?:则|那么|就|再)?(.+)\Z")
_CONDITIONAL_CAPACITY = re.compile(r"(?:若(.+?)足够[，,]?则|待客户确认(.+?)足够后)(.+)\Z")
_SCHEDULE = re.compile(r"(?:待|经|在)?(?:与)?(?:客户)?确认(?:首批上线时间|时间)?后(.+)\Z")
_RISK_SUBJECT = r"(?:试点部署|平台部署|部署|试点|建设|上线|交付|资料上传索引与检索链路)"
_RISK_EFFECT = r"(?:可能)?(?:受到影响|受阻|延期|无法(?:按期)?(?:在沿用环境中)?落地|无法上线)(?:，影响试点启动节奏)?"
_RISK = re.compile(r"(?:若|如果)(.+?)不满足(?:需求|部署条件)?(?:，?则" + _RISK_SUBJECT + _RISK_EFFECT + r")?\Z")
_RISK_IMPACT = re.compile(_RISK_SUBJECT + r"可能" + _RISK_EFFECT + r"\Z")
_GAP_RISK = re.compile(r"若(?:资源核验发现容量缺口[，,]?则可能影响试点|缺口未解决[，,]试点可能无法按约定范围开展)\Z")
_ASSERTION = re.compile(r"已经|已(?:确认|确定|完成|核验)|保证|确保|承诺|必然|一定|足够|足以|无需|无须|不用|不必|满足|具备|支持")


def _dependencies(text: str) -> tuple[str, ...]:
    # Only closed object names provide hints, never arbitrary semantic inference.
    result = []
    if re.search(r"容量|服务器|部署条件|部署需求|承载条件", text):
        result.append("deployment_requirement")
    if re.search(r"环境|数据库(?:配置|版本|扩展条件)|配置对本期部署", text):
        result.append("existing_environment")
    return tuple(result)


def explicit_plan_dependencies(text: str) -> tuple[str, ...]:
    """Closed object hints survive an unrecognized tail; never admit a clause."""
    return _dependencies(text) if isinstance(text, str) else ()


def _object(text: str) -> bool:
    return clarification_object_sequence(text) or re.fullmatch(_ASSESSMENT, text) is not None


def _clause(text: str) -> tuple[PlanClause, ...] | None:
    # Relations precede generic assertion detection; both sides are fully parsed.
    match = _SATISFIED.fullmatch(text)
    if match and _object(match[1]) and _WORK.fullmatch(match[2]):
        return (PlanClause(PlanClauseKind.CONDITIONAL_WORK, PlanPrerequisite.SATISFIED, _dependencies(match[1])),)
    match = _COMPLETED.fullmatch(text)
    if match and _WORK.fullmatch(match[1]):
        return (PlanClause(PlanClauseKind.CONDITIONAL_WORK, PlanPrerequisite.COMPLETED, _dependencies(text)),)
    match = _CONDITIONAL_CAPACITY.fullmatch(text)
    if match and _object(match[1] or match[2]) and _WORK.fullmatch(match[3]):
        return (PlanClause(PlanClauseKind.CONDITIONAL_WORK, PlanPrerequisite.SATISFIED, _dependencies(match[1] or match[2])),)
    match = _SCHEDULE.fullmatch(text)
    if match and _WORK.fullmatch(match[1]):
        return (PlanClause(PlanClauseKind.CONDITIONAL_WORK, PlanPrerequisite.COMPLETED, ()),)
    match = _PENDING_INQUIRY.fullmatch(text)
    if match:
        tail = _clause(match[1])
        if tail and all(item.kind is PlanClauseKind.INQUIRY for item in tail):
            return tail
    match = _RISK.fullmatch(text)
    if (match and _object(match[1])) or _RISK_IMPACT.fullmatch(text) or _GAP_RISK.fullmatch(text):
        return (PlanClause(PlanClauseKind.HYPOTHETICAL_RISK, dependencies=_dependencies(text)),)
    if _ARTIFACT.fullmatch(text):
        return (PlanClause(PlanClauseKind.PLANNED_ARTIFACT, dependencies=_dependencies(text)),)
    if _OUTCOME.fullmatch(text):
        return (PlanClause(PlanClauseKind.VERIFICATION_OUTCOME, dependencies=_dependencies(text)),)
    # Full action package remains one proposal externally; decomposition is internal.
    stripped = _PREFIX.sub("", text, count=1)
    if _ARTIFACT.fullmatch(stripped):
        return (PlanClause(PlanClauseKind.PLANNED_ARTIFACT, dependencies=_dependencies(stripped)),)
    parts = re.split(r"[，,]|(?<![，,])并(?=(?:" + _VERBS + r"|记录|形成|保证|确保))", stripped)
    if len(parts) > 1:
        nodes = tuple(_clause(part.strip()) for part in parts)
        if all(nodes):
            return tuple(node for group in nodes for node in group)
        return None
    match = _INQUIRY.fullmatch(stripped)
    if match:
        objects = _QUESTION.sub("", match[1])
        if _object(objects) or _BACKGROUND.fullmatch(objects):
            return (PlanClause(PlanClauseKind.INQUIRY, dependencies=_dependencies(objects)),)
    if clear_clarification_action(text):
        return (PlanClause(PlanClauseKind.INQUIRY, dependencies=_dependencies(text)),)
    if _ASSERTION.search(text):
        return (PlanClause(PlanClauseKind.ASSERTION, dependencies=_dependencies(text)),)
    return None


def parse_plan_expression(text: str) -> tuple[PlanClause, ...] | None:
    """Consume every clause, retaining prerequisite distinctions; fail closed."""
    if not isinstance(text, str) or not text.strip() or len(text) > 4000:
        return None
    statements = scoped_statements(text)
    groups = tuple(_clause(part) for part in statements)
    if not groups or not all(groups):
        return None
    return tuple(clause for group in groups for clause in group)
