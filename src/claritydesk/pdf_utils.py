"""Low-level PDF inspection & tagging helpers built on PyMuPDF (fitz).

This module is deliberately free of any agent logic: it only knows how to read
structure/colors/images out of a PDF and how to write tags/structure back in.
The agents compose these primitives.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional

import fitz  # PyMuPDF

# A line counts as "heading styled" if its largest span is at least this size.
HEADING_MIN_SIZE = 15.0
# WCAG 1.4.3 minimum contrast ratios.
CONTRAST_MIN_NORMAL = 4.5
CONTRAST_MIN_LARGE = 3.0
# Large-text threshold (pt). >=18pt, or >=14pt bold, is "large text" per WCAG.
LARGE_TEXT_SIZE = 18.0


# --------------------------------------------------------------------------- #
# Colour / contrast math (WCAG relative luminance)
# --------------------------------------------------------------------------- #
def int_to_rgb(color: int) -> tuple[float, float, float]:
    """PyMuPDF packs span colour as a single sRGB int."""
    return (((color >> 16) & 255) / 255.0,
            ((color >> 8) & 255) / 255.0,
            (color & 255) / 255.0)


def _channel(u: float) -> float:
    return u / 12.92 if u <= 0.03928 else ((u + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb: tuple[float, float, float]) -> float:
    r, g, b = (_channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg: tuple[float, float, float],
                   bg: tuple[float, float, float]) -> float:
    l1, l2 = relative_luminance(fg), relative_luminance(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def darken_to_contrast(fg: tuple[float, float, float],
                       bg: tuple[float, float, float],
                       target: float) -> tuple[float, float, float]:
    """Scale a colour toward black until it meets `target` contrast on `bg`.

    Returns the original colour if it already passes, else the darkest needed.
    """
    if contrast_ratio(fg, bg) >= target:
        return fg
    for step in range(1, 101):
        factor = 1.0 - step / 100.0
        cand = tuple(c * factor for c in fg)  # type: ignore[assignment]
        if contrast_ratio(cand, bg) >= target:  # type: ignore[arg-type]
            return cand  # type: ignore[return-value]
    return (0.0, 0.0, 0.0)


# --------------------------------------------------------------------------- #
# Text / image extraction
# --------------------------------------------------------------------------- #
@dataclass
class TextLine:
    page: int                  # 1-based
    text: str
    bbox: tuple[float, float, float, float]
    size: float                # largest span size in the line
    color: tuple[float, float, float]
    bold: bool

    @property
    def is_heading_styled(self) -> bool:
        return self.size >= HEADING_MIN_SIZE or (self.bold and self.size >= 13.0)

    @property
    def is_large_text(self) -> bool:
        return self.size >= LARGE_TEXT_SIZE or (self.bold and self.size >= 14.0)


def iter_text_lines(page: fitz.Page, page_no: int) -> Iterable[TextLine]:
    data = page.get_text("dict")
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue
            text = "".join(s["text"] for s in line["spans"]).strip()
            if not text:
                continue
            top = max(spans, key=lambda s: s["size"])
            bold = "bold" in top.get("font", "").lower() or bool(top.get("flags", 0) & 2 ** 4)
            yield TextLine(
                page=page_no,
                text=text,
                bbox=tuple(line["bbox"]),
                size=round(float(top["size"]), 2),
                color=int_to_rgb(int(top.get("color", 0))),
                bold=bold,
            )


def page_background(page: fitz.Page) -> tuple[float, float, float]:
    """Best-effort page background colour. Defaults to white when undetermined."""
    for d in page.get_drawings():
        if d.get("fill") and d.get("rect"):
            r = fitz.Rect(d["rect"])
            if r.width >= page.rect.width * 0.9 and r.height >= page.rect.height * 0.9:
                f = d["fill"]
                return (float(f[0]), float(f[1]), float(f[2]))
    return (1.0, 1.0, 1.0)


def list_images(page: fitz.Page) -> list[int]:
    """Distinct image xrefs placed on the page."""
    seen: list[int] = []
    for info in page.get_images(full=True):
        xref = info[0]
        if xref not in seen:
            seen.append(xref)
    return seen


# --------------------------------------------------------------------------- #
# Document-level catalog reads
# --------------------------------------------------------------------------- #
def has_title(doc: fitz.Document) -> bool:
    return bool((doc.metadata or {}).get("title", "").strip())


def display_doc_title(doc: fitz.Document) -> bool:
    cat = doc.pdf_catalog()
    typ, vp = doc.xref_get_key(cat, "ViewerPreferences")
    return bool(vp and "DisplayDocTitle" in vp and "true" in vp.lower())


def get_language(doc: fitz.Document) -> Optional[str]:
    cat = doc.pdf_catalog()
    typ, val = doc.xref_get_key(cat, "Lang")
    return val if typ == "string" else None


def is_marked(doc: fitz.Document) -> bool:
    cat = doc.pdf_catalog()
    typ, val = doc.xref_get_key(cat, "MarkInfo")
    return bool(val and "Marked" in val and "true" in val.lower())


def struct_tree_root(doc: fitz.Document) -> Optional[int]:
    cat = doc.pdf_catalog()
    typ, val = doc.xref_get_key(cat, "StructTreeRoot")
    if typ == "xref":
        return int(val.split()[0])
    return None


# --------------------------------------------------------------------------- #
# Structure-tree read
# --------------------------------------------------------------------------- #
def _refs(val: str) -> list[int]:
    return [int(n) for n in re.findall(r"(\d+) 0 R", val or "")]


@dataclass
class StructElem:
    xref: int
    s: str                       # role, e.g. "H1", "Figure", "Document"
    alt: Optional[str]
    actual_text: Optional[str]


def read_struct_elements(doc: fitz.Document) -> list[StructElem]:
    """Flatten every structure element in the tree (depth-first)."""
    root = struct_tree_root(doc)
    out: list[StructElem] = []
    if not root:
        return out

    def visit(xref: int, seen: set[int]) -> None:
        if xref in seen:
            return
        seen.add(xref)
        _, s = doc.xref_get_key(xref, "S")
        if s:
            _, alt = doc.xref_get_key(xref, "Alt")
            _, at = doc.xref_get_key(xref, "ActualText")
            out.append(StructElem(
                xref=xref,
                s=s.lstrip("/"),
                alt=None if alt in (None, "null") else _unescape(alt),
                actual_text=None if at in (None, "null") else _unescape(at),
            ))
        _, k = doc.xref_get_key(xref, "K")
        if k:
            for c in _refs(k):
                visit(c, seen)

    _, k = doc.xref_get_key(root, "K")
    for c in _refs(k or ""):
        visit(c, set())
    return out


def figures_with_alt(doc: fitz.Document) -> list[StructElem]:
    return [e for e in read_struct_elements(doc)
            if e.s.lower() == "figure" and (e.alt or "").strip()]


def heading_elements(doc: fitz.Document) -> list[StructElem]:
    return [e for e in read_struct_elements(doc)
            if re.fullmatch(r"H[1-6]?", e.s)]


# --------------------------------------------------------------------------- #
# Structure-tree write
# --------------------------------------------------------------------------- #
def _escape(text: str) -> str:
    """Escape a string for a PDF literal-string ( ... )."""
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _unescape(text: str) -> str:
    return text.replace(r"\(", "(").replace(r"\)", ")").replace(r"\\", "\\")


def _new_obj(doc: fitz.Document, body: str) -> int:
    xref = doc.get_new_xref()
    doc.update_object(xref, body)
    return xref


def ensure_tagged(doc: fitz.Document) -> int:
    """Ensure the document is marked tagged and return the StructTreeRoot xref.

    Creates an empty Document-rooted structure tree if none exists.
    """
    cat = doc.pdf_catalog()
    doc.xref_set_key(cat, "MarkInfo", "<< /Marked true >>")
    root = struct_tree_root(doc)
    if root is None:
        document = _new_obj(doc, "<< /Type /StructElem /S /Document /K [ ] >>")
        root = _new_obj(
            doc,
            "<< /Type /StructTreeRoot "
            "/RoleMap << /Document /Sect >> "
            f"/K [ {document} 0 R ] >>",
        )
        doc.xref_set_key(cat, "StructTreeRoot", f"{root} 0 R")
    return root


def _document_elem(doc: fitz.Document, root: int) -> int:
    _, k = doc.xref_get_key(root, "K")
    refs = _refs(k or "")
    if refs:
        return refs[0]
    document = _new_obj(doc, "<< /Type /StructElem /S /Document /K [ ] >>")
    doc.xref_set_key(root, "K", f"[ {document} 0 R ]")
    return document


def _append_child(doc: fitz.Document, parent: int, child: int) -> None:
    _, k = doc.xref_get_key(parent, "K")
    refs = _refs(k or "")
    refs.append(child)
    inner = " ".join(f"{r} 0 R" for r in refs)
    doc.xref_set_key(parent, "K", f"[ {inner} ]")


def add_figure(doc: fitz.Document, alt: str) -> int:
    """Add a Figure structure element with /Alt under the Document element."""
    root = ensure_tagged(doc)
    document = _document_elem(doc, root)
    fig = _new_obj(
        doc,
        f"<< /Type /StructElem /S /Figure /P {document} 0 R "
        f"/Alt ({_escape(alt)}) >>",
    )
    _append_child(doc, document, fig)
    return fig


def add_heading(doc: fitz.Document, level: int, text: str) -> int:
    """Add an H{level} structure element carrying the heading text."""
    level = max(1, min(6, level))
    root = ensure_tagged(doc)
    document = _document_elem(doc, root)
    h = _new_obj(
        doc,
        f"<< /Type /StructElem /S /H{level} /P {document} 0 R "
        f"/ActualText ({_escape(text)}) >>",
    )
    _append_child(doc, document, h)
    return h


def set_title(doc: fitz.Document, title: str) -> None:
    meta = doc.metadata or {}
    meta["title"] = title
    doc.set_metadata(meta)
    cat = doc.pdf_catalog()
    doc.xref_set_key(cat, "ViewerPreferences", "<< /DisplayDocTitle true >>")


def set_language(doc: fitz.Document, lang: str = "en-US") -> None:
    cat = doc.pdf_catalog()
    doc.xref_set_key(cat, "Lang", f"({lang})")
