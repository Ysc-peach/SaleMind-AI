"""Safe knowledge document parsing entry points."""

from .factory import parse_document
from .types import ParsedSegment


__all__ = ["ParsedSegment", "parse_document"]
