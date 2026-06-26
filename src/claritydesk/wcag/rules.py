"""WCAG 2.1 / PDF-UA rule catalog implemented by ClarityDesk.

Each rule maps a ClarityDesk check id to the underlying WCAG Success Criterion
so that every flagged violation and every applied fix can be traced back to the
specific rule it was meant to satisfy (the "verify against the rule" loop).

ClarityDesk implements a practical, high-impact subset of WCAG 2.1 and PDF/UA.
It is not a full conformance certifier; see docs/ARCHITECTURE.md for the exact
scope and known limitations.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    id: str            # ClarityDesk check id, e.g. "image-alt"
    sc: str            # WCAG Success Criterion number, e.g. "1.1.1"
    name: str          # Human readable SC name
    level: str         # A / AA / AAA
    wcag_url: str      # Canonical WCAG quick-ref anchor
    summary: str       # What the check verifies / why it matters
    how_to_fix: str    # What the remediation agent does


_QR = "https://www.w3.org/WAI/WCAG21/quickref/#"

RULES: dict[str, Rule] = {
    "doc-title": Rule(
        id="doc-title",
        sc="2.4.2",
        name="Page Titled",
        level="A",
        wcag_url=_QR + "page-titled",
        summary="The document must declare a descriptive title and show it in the "
                "title bar (ViewerPreferences /DisplayDocTitle true).",
        how_to_fix="Set the document title metadata and enable DisplayDocTitle.",
    ),
    "doc-language": Rule(
        id="doc-language",
        sc="3.1.1",
        name="Language of Page",
        level="A",
        wcag_url=_QR + "language-of-page",
        summary="The document's default human language must be programmatically set "
                "(catalog /Lang) so screen readers pronounce content correctly.",
        how_to_fix="Set the catalog /Lang entry (defaults to en-US, configurable).",
    ),
    "tagged-pdf": Rule(
        id="tagged-pdf",
        sc="1.3.1",
        name="Info and Relationships",
        level="A",
        wcag_url=_QR + "info-and-relationships",
        summary="The PDF must be a Tagged PDF: /MarkInfo /Marked true and a "
                "/StructTreeRoot describing reading order and structure.",
        how_to_fix="Mark the document tagged and build a structure tree root.",
    ),
    "image-alt": Rule(
        id="image-alt",
        sc="1.1.1",
        name="Non-text Content",
        level="A",
        wcag_url=_QR + "non-text-content",
        summary="Every meaningful image must expose a text alternative (a Figure "
                "structure element with a non-empty /Alt).",
        how_to_fix="Generate context-aware alt text and attach a Figure/Alt element.",
    ),
    "heading-tagged": Rule(
        id="heading-tagged",
        sc="1.3.1",
        name="Info and Relationships (Headings)",
        level="A",
        wcag_url=_QR + "info-and-relationships",
        summary="Text that is visually styled as a heading must be tagged with a "
                "real heading structure element (H1/H2/...).",
        how_to_fix="Detect heading-styled lines and add H-level structure elements.",
    ),
    "bookmarks": Rule(
        id="bookmarks",
        sc="2.4.5",
        name="Multiple Ways",
        level="AA",
        wcag_url=_QR + "multiple-ways",
        summary="Multi-page documents should offer document outline bookmarks so "
                "users can navigate without reading every page.",
        how_to_fix="Generate an outline (bookmarks) from the detected headings.",
    ),
    "contrast": Rule(
        id="contrast",
        sc="1.4.3",
        name="Contrast (Minimum)",
        level="AA",
        wcag_url=_QR + "contrast-minimum",
        summary="Body text must have a contrast ratio of at least 4.5:1 against its "
                "background (3:1 for large text).",
        how_to_fix="Darken low-contrast text to meet the minimum ratio.",
    ),
}


def get_rule(rule_id: str) -> Rule:
    try:
        return RULES[rule_id]
    except KeyError as exc:  # pragma: no cover - defensive
        raise KeyError(f"Unknown ClarityDesk rule id: {rule_id!r}") from exc
