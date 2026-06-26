"""Shared data models passed between the Scanning, Remediation and Verification agents."""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

from .wcag import get_rule


@dataclass
class Violation:
    """A single WCAG violation flagged by the Scanning Agent."""
    rule_id: str                      # maps to wcag.RULES
    page: int                         # 1-based; 0 = document-level
    message: str                      # human readable description of the problem
    target: str = ""                  # element identifier (e.g. image xref, text snippet)
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def sc(self) -> str:
        return get_rule(self.rule_id).sc

    @property
    def level(self) -> str:
        return get_rule(self.rule_id).level

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["sc"] = self.sc
        d["level"] = self.level
        d["rule_name"] = get_rule(self.rule_id).name
        return d


@dataclass
class RemediationAction:
    """A fix applied by the Remediation Agent for one violation."""
    rule_id: str
    page: int
    target: str
    description: str                  # what was changed
    generated: dict[str, Any] = field(default_factory=dict)  # e.g. {"alt_text": "..."}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VerificationItem:
    """Result of re-checking one originally-flagged violation against its rule."""
    rule_id: str
    page: int
    target: str
    resolved: bool
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScanResult:
    source: str
    sha256: str
    pages: int
    violations: list[Violation] = field(default_factory=list)
    scanned_at: float = field(default_factory=time.time)

    @property
    def count(self) -> int:
        return len(self.violations)

    def by_rule(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for v in self.violations:
            out[v.rule_id] = out.get(v.rule_id, 0) + 1
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "sha256": self.sha256,
            "pages": self.pages,
            "count": self.count,
            "by_rule": self.by_rule(),
            "violations": [v.to_dict() for v in self.violations],
            "scanned_at": self.scanned_at,
        }


@dataclass
class ComplianceReport:
    """End-to-end audit result produced by the Orchestrator."""
    source: str
    output: Optional[str]
    before: ScanResult
    after: ScanResult
    actions: list[RemediationAction] = field(default_factory=list)
    verification: list[VerificationItem] = field(default_factory=list)
    generated_at: float = field(default_factory=time.time)

    @property
    def before_count(self) -> int:
        return self.before.count

    @property
    def after_count(self) -> int:
        return self.after.count

    @property
    def resolved_count(self) -> int:
        return sum(1 for v in self.verification if v.resolved)

    @property
    def passed(self) -> bool:
        return self.after_count == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "output": self.output,
            "passed": self.passed,
            "before_count": self.before_count,
            "after_count": self.after_count,
            "resolved_count": self.resolved_count,
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
            "actions": [a.to_dict() for a in self.actions],
            "verification": [v.to_dict() for v in self.verification],
            "generated_at": self.generated_at,
        }
