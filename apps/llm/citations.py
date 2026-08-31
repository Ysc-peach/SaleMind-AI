"""Pure citation formatting; labels are always supplied by application code."""

import re


_GROUP = r"\s*S[0-9]+(?:\s*[,、，]\s*S[0-9]+)*\s*"
_CITATION_GROUP_PATTERN = re.compile(
    rf"\[(?P<bracket>{_GROUP})\]|\((?P<ascii>{_GROUP})\)|（(?P<cjk>{_GROUP})）"
)


def normalize_citations(answer: str, *, source_count: int) -> str:
    """Only normalize complete groups whose exact labels all exist.

    Compare labels as strings: S01 is not S1, and untrusted huge numbers never
    enter Python's integer parser. Unknown/mixed groups remain unchanged.
    """
    allowed = {f"S{i}" for i in range(1, source_count + 1)}

    def replace_group(match: re.Match[str]) -> str:
        body = next(group for group in match.groups() if group is not None)
        labels = re.findall(r"S[0-9]+", body)
        if not all(label in allowed for label in labels):
            return match.group(0)
        return "".join(f"[{label}]" for label in labels)

    return _CITATION_GROUP_PATTERN.sub(replace_group, answer)


def has_unknown_citations(text: str, *, source_count: int) -> bool:
    """Recognize the same small token grammar, not arbitrary prose or NLP."""
    allowed = {f"S{i}" for i in range(1, source_count + 1)}
    for match in _CITATION_GROUP_PATTERN.finditer(text):
        body = next(group for group in match.groups() if group is not None)
        if any(label not in allowed for label in re.findall(r"S[0-9]+", body)):
            return True
    return False
