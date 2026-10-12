"""Structured validation findings shared by parsers and validators."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from dataclasses import field as dc_field
from enum import Enum
from typing import Any


class Severity(str, Enum):
    ERROR = "error"  # record cannot be used for analysis
    WARNING = "warning"  # usable, but a limitation the analyst must see
    INFO = "info"  # noteworthy, no effect on usability


@dataclass
class Finding:
    severity: Severity
    code: str
    message: str
    record: str | None = None  # object id / line reference
    field: str | None = None
    suggestion: str | None = None  # proposed correction; never applied automatically
    context: dict[str, Any] = dc_field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["severity"] = self.severity.value
        return d


def has_errors(findings: list[Finding]) -> bool:
    return any(f.severity is Severity.ERROR for f in findings)
