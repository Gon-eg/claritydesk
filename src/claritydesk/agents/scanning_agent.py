"""Scanning Agent - parses document structure and flags WCAG violations.

This is the "plan" stage of the plan -> act -> verify loop. It reads the PDF and
emits a rich `ScanResult` whose `Violation` objects carry enough detail
(bounding boxes, colours, sizes, image context) for the Remediation Agent to act
without re-parsing the document.
"""
from __future__ import annotations

import re
from typing import Optional

import fitz

from .. import pdf_utils as pu
from ..models import ScanResult, Violation

_CAPTION_RE = re.compile(r"^(figure|fig\.?|table|chart|exhibit|image)\b", re.I)


def _image_context(page: fitz.Page, page_no: int, xref: int,
                   lines: list[pu.TextLine]) -> dict:
    """Find a caption / nearest heading / surrounding text for an image."""
    rects = page.get_image_rects(xref)
    rect = rects[0] if rects else page.rect
    cy = (rect.y0 + rect.y1) / 2

    caption = ""
    heading = ""
    nearby: list[str] = []
    best_cap_dist = 1e9
    for ln in lines:
        lcy = (ln.bbox[1] + ln.bbox[3]) / 2
        dist = abs(lcy - cy)
        if _CAPTION_RE.match(ln.text) and dist < best_cap_dist:
            caption, best_cap_dist = ln.text, dist
        if ln.is_heading_styled and ln.bbox[1] <= rect.y0:
            heading = ln.text  # last heading above the image wins
        if dist < rect.height + 60:
            nearby.append(ln.text)
    return {
        "caption": caption,
        "heading": heading,
        "surrounding_text": " ".join(nearby[:4]),
    }


def scan_document(doc: fitz.Document, source: str, sha256: str) -> ScanResult:
    """Run every implemented WCAG check against an open document."""
    violations: list[Violation] = []
    pages = doc.page_count

    # ---- document-level checks -------------------------------------------- #
    if not (pu.has_title(doc) and pu.display_doc_title(doc)):
        violations.append(Violation(
            "doc-title", 0,
            "Document has no descriptive title / DisplayDocTitle is not set."))

    if not pu.get_language(doc):
        violations.append(Violation(
            "doc-language", 0,
            "Document default language (catalog /Lang) is not set."))

    if not (pu.is_marked(doc) and pu.struct_tree_root(doc) is not None):
        violations.append(Violation(
            "tagged-pdf", 0,
            "Document is not a Tagged PDF (missing /MarkInfo Marked or "
            "/StructTreeRoot)."))

    if pages >= 3 and not doc.get_toc():
        violations.append(Violation(
            "bookmarks", 0,
            f"{pages}-page document has no navigational bookmarks/outline."))

    # ---- structure available for matching --------------------------------- #
    tagged_headings = {(_norm(e.actual_text or "")) for e in pu.heading_elements(doc)}
    figures_alt = pu.figures_with_alt(doc)
    figure_budget = len(figures_alt)  # each covers one image, in document order

    image_index = 0
    # ---- per-page checks --------------------------------------------------- #
    for pno in range(pages):
        page = doc[pno]
        page_no = pno + 1
        lines = list(pu.iter_text_lines(page, page_no))
        bg = pu.page_background(page)

        # contrast (1.4.3)
        for ln in lines:
            need = pu.CONTRAST_MIN_LARGE if ln.is_large_text else pu.CONTRAST_MIN_NORMAL
            ratio = pu.contrast_ratio(ln.color, bg)
            if ratio + 1e-9 < need:
                violations.append(Violation(
                    "contrast", page_no,
                    f"Text contrast {ratio:.2f}:1 is below the {need:.1f}:1 "
                    f"minimum: '{_short(ln.text)}'",
                    target=_short(ln.text, 40),
                    details={"text": ln.text, "bbox": list(ln.bbox),
                             "color": list(ln.color), "bg": list(bg),
                             "size": ln.size, "need": need,
                             "ratio": round(ratio, 2)}))

        # heading tagged (1.3.1)
        for ln in lines:
            if ln.is_heading_styled and _norm(ln.text) not in tagged_headings:
                violations.append(Violation(
                    "heading-tagged", page_no,
                    f"Heading-styled text is not tagged as a heading: "
                    f"'{_short(ln.text)}'",
                    target=_short(ln.text, 40),
                    details={"text": ln.text, "size": ln.size,
                             "level": 1 if ln.size >= 20 else 2,
                             "bbox": list(ln.bbox)}))

        # image alt text (1.1.1)
        for xref in pu.list_images(page):
            covered = image_index < figure_budget
            image_index += 1
            if covered:
                continue
            ctx = _image_context(page, page_no, xref, lines)
            violations.append(Violation(
                "image-alt", page_no,
                f"Image (xref {xref}) on page {page_no} has no text alternative.",
                target=f"page{page_no}-img{xref}",
                details={"xref": xref, **ctx}))

    return ScanResult(source=source, sha256=sha256, pages=pages,
                      violations=violations)


class ScanningAgent:
    """Thin agent wrapper around `scan_document` (open + scan + close)."""

    name = "scanning-agent"

    def scan_path(self, path: str, sha256: str) -> ScanResult:
        doc = fitz.open(path)
        try:
            return scan_document(doc, source=path, sha256=sha256)
        finally:
            doc.close()

    def scan_open(self, doc: fitz.Document, source: str, sha256: str) -> ScanResult:
        return scan_document(doc, source=source, sha256=sha256)


def _short(text: str, n: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "\u2026"


def _norm(text: str) -> str:
    return " ".join((text or "").split()).strip().lower()
