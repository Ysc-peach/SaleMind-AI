"""Bounded clarification grammar, not general intent or fact classification.

Only complete assessment/action clauses qualify. Recognition grants no fact,
capability, precision, atomicity or semantic-verifier authority.
"""

import re


_OBJECT = (
    r"(?:客户)?(?:现有|可用|当前|目标|本期)?"
    r"(?:服务器(?:资源|容量|配置)?|资源(?:容量|需求)?|容量|性能指标|"
    r"部署(?:条件|环境|资源|边界)|实施边界|环境可用性|环境|运行环境|数据库(?:版本|扩展条件|配置)|"
    r"并发(?:需求|负载)|用户规模|接口(?:协议|能力)|预算(?:口径)?|"
    r"上线时间|实施日期|验收条件|权限(?:配置|映射)|(?:网络)?访问边界|资料范围|文档格式)"
)
_PREFIX = (
    r"(?:并且|同时|然后|并|再)?(?:建议|计划|拟|应|需|需要)?"
    r"(?:在)?(?:(?:实施|部署|上线|验收|联调|试点)前|试点期间)?(?:先|优先)?"
)
# A bounded project qualifier names the subject of inquiry, never its outcome.
_PROJECT_SCOPE = r"(?:(?:本期|本阶段)?(?:试点|项目)(?:在(?:现有|目标)环境中|实施所依赖)?的)?"
# A bounded ASCII product name can qualify the environment being investigated.
# The qualifier ends before the closed object list: no result, Chinese assertion
# or arbitrary free-text tail may be consumed as an environment name. Naming a
# target is not evidence it exists or is usable; semantic admission still vets it.
_ENVIRONMENT_NAME = r"[A-Za-z][A-Za-z0-9_-]{0,31}(?: [A-Za-z][A-Za-z0-9_-]{0,31}){0,3}"
_ENVIRONMENT_SCOPE = r"(?:(?:现有|当前|目标)(?:" + _ENVIRONMENT_NAME + r")?(?:运行)?环境的)?"
_QUALIFIED_OBJECT = _ENVIRONMENT_SCOPE + _OBJECT
# Shared planning objects extend inquiry qualifiers, not the legacy action gate.
_PLAN_ENVIRONMENT_SCOPE = (
    r"(?:(?:现有|当前|目标|沿用)\s*(?:" + _ENVIRONMENT_NAME
    + r"\s*)?(?:运行)?环境的)?"
)
_PLAN_OBJECT_SEQUENCE = re.compile(
    _PLAN_ENVIRONMENT_SCOPE + _OBJECT
    + r"(?:\s*[、和与及]\s*" + _PLAN_ENVIRONMENT_SCOPE + _OBJECT + r")*\Z"
)
_ACTION = re.compile(
    _PREFIX + r"(?:"
    r"(?:核对|核验|验证|评估|确认|测量|检查|测试|收集|统计)"
    + _PROJECT_SCOPE + _QUALIFIED_OBJECT + r"(?:[、和与及]" + _QUALIFIED_OBJECT + r")*"
    r"(?:(?:是否|能否)(?:满足(?:本期)?(?:部署)?需求|符合部署条件|足够|可用))?"
    r"|(?:开展|进行|执行)?(?:容量评估|容量核验|容量验证|资源核验|资源盘点|环境核验|性能验证|并发测试|权限核验)"
    r"|(?:记录|形成)(?:核对|核验|验证|评估|检查|测试|测量|统计)(?:结果|记录|报告)"
    r")\Z"
)
_STATEMENT_SEPARATOR = re.compile(r"[。!！?？;；\r\n]+|(?<!\d)\.(?!\d)")
_CONSEQUENCE_SEPARATOR = re.compile(r"[，,]|则|那么|就|再")
_CONSEQUENCE_CONNECTOR = re.compile(r"^(?:则|那么|就|再)\s*")
_ASSERTIVE_CONSEQUENCE = re.compile(
    r"已经|已(?:确认|确定|完成)|满足|具备|支持|足够|足以|保证|确保|承诺|必然|一定|"
    r"(?:无需|无须|不用|不必)(?:确认|核对|核验|验证|评估)"
)


def clear_clarification_action(text: str) -> bool:
    """Require every whole clause to match the closed action grammar."""
    clauses = tuple(part.strip() for part in re.split(r"[，,。!！?？;；\r\n]+|(?<!\d)\.(?!\d)", text) if part.strip())
    return bool(clauses) and all(_ACTION.fullmatch(part) is not None for part in clauses)


def clarification_object_sequence(text: str) -> bool:
    """Recognize complete closed inquiry objects; no intent or admission."""
    return isinstance(text, str) and _PLAN_OBJECT_SEQUENCE.fullmatch(text.strip()) is not None


def scoped_statements(text: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in _STATEMENT_SEPARATOR.split(text) if part.strip())


def conditional_parts(text: str) -> tuple[str, str]:
    """Separate one explicit prerequisite from its following consequence."""
    parts = _CONSEQUENCE_SEPARATOR.split(text, maxsplit=1)
    if len(parts) == 2:
        return parts[0], normalized_consequence(parts[1])
    return text, text


def normalized_consequence(text: str) -> str:
    """Strip one bounded connective, never assertion or promise content."""
    return _CONSEQUENCE_CONNECTOR.sub("", text.lstrip("，, "), count=1)


def assertive_consequence(text: str) -> bool:
    return _ASSERTIVE_CONSEQUENCE.search(text) is not None
