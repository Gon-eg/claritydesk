"""Remediation Agent - turns each flagged violation into a concrete fix.

This is the "act" stage. It consumes the rich `ScanResult` from the Scanning
Agent and mutates the document in place:

* doc-title     -> set descriptive title + DisplayDocTitle
* doc-language  -> set catalog /Lang
* tagged-pdf    -> mark tagged + create StructTreeRoot
* heading-tagged-> add H1/H2 structure elements
* image-alt     -> generate context-aware alt text + add Figure/Alt elements
* bookmarks     -> build an outline from detected headings
* contrast      -> darken text to meet the WCAG minimum ratio

It never invents data silently: every change is recorded as a `RemediationAction`.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Optional

import fitz

from .. import pdf_utils as pu
from ..alt_text import AltTextProvider, ImageContext, default_provider
from ..models import RemediationAction, ScanResult, Violation


class RemediationAgent:
    name = "remediation-agent"

    def __init__(self, alt_provider: Optional[AltTextProvider] = None,
                 language: str = "en-US"):
        self.alt_provider = alt_provider or default_provider()
        self.language = language

    # ------------------------------------------------------------------ #
    def remediate(self, doc: fitz.Document, scan: ScanResult) -> list[RemediationAction]:
        actions: list[RemediationAction] = []
        groups: dict[str, list[Violation]] = defaultdict(list)
        for v in scan.violations:
            groups[v.rule_id].append(v)

        # Make sure the structure tree exists before adding headings/figures.
        if groups.get("tagged-pdf") or groups.get("heading-tagged") or groups.get("image-alt"):
            pu.ensure_tagged(doc)

        if groups.get("tagged-pdf"):
            actions.append(RemediationAction(
                "tagged-pdf", 0, "document",
                "Marked document as Tagged PDF and created a StructTreeRoot."))

        # ---- title -------------------------------------------------------- #
        if groups.get("doc-title"):
            title = self._derive_title(doc, scan)
            pu.set_title(doc, title)
            actions.append(RemediationAction(
                "doc-title", 0, "document",
                f"Set document title and enabled DisplayDocTitle.",
                generated={"title": title}))

        # ---- language ----------------------------------------------------- #
        if groups.get("doc-language"):
            pu.set_language(doc, self.language)
            actions.append(RemediationAction(
                "doc-language", 0, "document",
                f"Set document language to {self.language}.",
                generated={"lang": self.language}))

        # ---- headings ----------------------------------------------------- #
        for v in groups.get("heading-tagged", []):
            text = v.details.get("text", v.target)
            level = int(v.details.get("level", 2))
            pu.add_heading(doc, level, text)
            actions.append(RemediationAction(
                "heading-tagged", v.page, v.target,
                f"Tagged heading-styled text as H{level}.",
                generated={"level": level, "text": text}))

        # ---- image alt text ---------------------------------------------- #
        for v in groups.get("image-alt", []):
            alt = self._alt_for(doc, v)
            pu.add_figure(doc, alt)
            actions.append(RemediationAction(
                "image-alt", v.page, v.target,
                "Generated alt text and attached a Figure/Alt structure element.",
                generated={"alt_text": alt, "provider": self.alt_provider.name}))

        # ---- bookmarks ---------------------------------------------------- #
        if groups.get("bookmarks"):
            toc = self._build_toc(scan)
            if toc:
                doc.set_toc(toc)
                actions.append(RemediationAction(
                    "bookmarks", 0, "document",
                    f"Generated {len(toc)} outline bookmarks from headings.",
                    generated={"entries": [t[1] for t in toc]}))

        # ---- contrast (grouped per page; redact then reinsert) ----------- #
        contrast_by_page: dict[int, list[Violation]] = defaultdict(list)
        for v in groups.get("contrast", []):
            contrast_by_page[v.page].append(v)
        for page_no, vs in contrast_by_page.items():
            actions.extend(self._fix_contrast(doc, page_no, vs))

        return actions

    # ------------------------------------------------------------------ #
    def _alt_for(self, doc: fitz.Document, v: Violation) -> str:
        xref = int(v.details["xref"])
        try:
            raw = doc.extract_image(xref)
            data = raw["image"]
        except Exception:
            data = b""
        ctx = ImageContext(
            image_bytes=data, page=v.page, xref=xref,
            caption=v.details.get("caption", ""),
            heading=v.details.get("heading", ""),
            surrounding_text=v.details.get("surrounding_text", ""),
        )
        alt = self.alt_provider.describe(ctx).strip()
        return alt or "Decorative or unlabeled image (review recommended)."

    def _derive_title(self, doc: fitz.Document, scan: ScanResult) -> str:
        for v in scan.violations:
            if v.rule_id == "heading-tagged" and v.details.get("level") == 1:
                return v.details.get("text", "").strip() or Path(scan.source).stem
        # fall back to first heading-styled line, else filename
        for v in scan.violations:
            if v.rule_id == "heading-tagged":
                return v.details.get("text", "").strip() or Path(scan.source).stem
        return Path(scan.source).stem.replace("_", " ").title()

    def _build_toc(self, scan: ScanResult) -> list[list]:
        toc: list[list] = []
        for v in scan.violations:
            if v.rule_id == "heading-tagged":
                level = int(v.details.get("level", 2))
                text = v.details.get("text", v.target).strip()
                if text:
                    toc.append([min(level, 2), text, v.page])
        return toc

    def _fix_contrast(self, doc: fitz.Document, page_no: int,
                      vs: list[Violation]) -> list[RemediationAction]:
        page = doc[page_no - 1]
        plans = []
        for v in vs:
            d = v.details
            fg = tuple(d["color"]); bg = tuple(d["bg"])
            # Meet at least the required ratio, but aim for an AAA-level (7:1)
            # margin so the fix is comfortably legible, not borderline.
            target = max(float(d["need"]), 7.0)
            new = pu.darken_to_contrast(fg, bg, target)
            plans.append((v, fitz.Rect(d["bbox"]), d["size"], new))
            page.add_redact_annot(fitz.Rect(d["bbox"]), fill=tuple(bg))
        # apply once, keeping images intact
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        actions = []
        for v, rect, size, new in plans:
            page.insert_text((rect.x0, rect.y1 - max(2.0, size * 0.18)),
                             v.details.get("text", ""), color=new,
                             fontsize=size, fontname="helv")
            actions.append(RemediationAction(
                "contrast", page_no, v.target,
                f"Darkened low-contrast text to meet "
                f"{v.details['need']:.1f}:1.",
                generated={"new_color": [round(c, 3) for c in new]}))
        return actions
