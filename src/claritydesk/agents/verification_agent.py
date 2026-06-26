"""Verification Agent - re-checks the remediated document against WCAG rules.

This is the "verify" stage. It re-runs the exact same checks on the output and
confirms that each originally-flagged violation is gone. It also surfaces any
*residual* or newly-introduced violations so a fix is never trusted blindly.
The audit only "passes" when the after-count reaches zero.
"""
from __future__ import annotations

import fitz

from ..models import ScanResult, VerificationItem, Violation
from .scanning_agent import scan_document

_DOC_LEVEL = {"doc-title", "doc-language", "tagged-pdf", "bookmarks"}


class VerificationAgent:
    name = "verification-agent"

    def verify(self, doc: fitz.Document, before: ScanResult,
               source: str, sha256: str) -> tuple[ScanResult, list[VerificationItem]]:
        after = scan_document(doc, source=source, sha256=sha256)

        # index residual violations for fast lookup
        residual_doc_rules = {v.rule_id for v in after.violations if v.rule_id in _DOC_LEVEL}
        residual_targets = {(v.rule_id, v.target) for v in after.violations}

        items: list[VerificationItem] = []
        for v in before.violations:
            if v.rule_id in _DOC_LEVEL:
                resolved = v.rule_id not in residual_doc_rules
            else:
                resolved = (v.rule_id, v.target) not in residual_targets
            items.append(VerificationItem(
                rule_id=v.rule_id, page=v.page, target=v.target,
                resolved=resolved,
                note="Verified against WCAG " + v.sc if resolved
                     else "Still failing after remediation"))

        # flag any brand-new violations introduced by remediation (regressions)
        before_keys = {(v.rule_id, v.target) for v in before.violations}
        for v in after.violations:
            if (v.rule_id, v.target) not in before_keys:
                items.append(VerificationItem(
                    rule_id=v.rule_id, page=v.page, target=v.target,
                    resolved=False,
                    note="New/residual violation introduced during remediation"))

        return after, items
