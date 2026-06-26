"""Generate a realistic, deliberately *inaccessible* sample PDF for the demo.

The sample mimics an SMB HR/policy handbook and is engineered to contain a
known set of WCAG violations (18 total) so the before/after is reproducible:

  doc-title       x1   (no title / DisplayDocTitle)
  doc-language    x1   (no catalog /Lang)
  tagged-pdf      x1   (untagged, no StructTreeRoot)
  bookmarks       x1   (3 pages, no outline)
  heading-tagged  x4   (1 title + 3 section headings, untagged)
  contrast        x7   (light-grey body lines below 4.5:1)
  image-alt       x3   (logo, chart, photo - no alt text)
  --------------------------------
  total           18

Run:  python examples/generate_sample.py [output.pdf]
"""
from __future__ import annotations

import io
import math
import sys
from pathlib import Path

import fitz
from PIL import Image, ImageDraw

GREY = (0.62, 0.62, 0.62)   # ~2.7:1 on white -> fails 1.4.3
DARK = (0.16, 0.16, 0.16)   # passes
BLACK = (0, 0, 0)


# --------------------------------------------------------------------------- #
# Image assets (kept simple + deterministic, no external files needed)
# --------------------------------------------------------------------------- #
def _logo() -> bytes:
    img = Image.new("RGB", (320, 160), "white")
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([20, 30, 130, 130], radius=18, fill=(20, 80, 160))
    d.ellipse([60, 60, 100, 100], fill="white")
    d.text((150, 65), "ClarityDesk", fill=(20, 80, 160))
    return _png(img)


def _chart() -> bytes:
    img = Image.new("RGB", (480, 300), "white")
    d = ImageDraw.Draw(img)
    vals = [120, 180, 90, 220]
    labels = ["Q1", "Q2", "Q3", "Q4"]
    for i, (v, lab) in enumerate(zip(vals, labels)):
        x = 60 + i * 100
        d.rectangle([x, 260 - v, x + 60, 260], fill=(40, 130, 200))
        d.text((x + 20, 268), lab, fill=(60, 60, 60))
    d.line([50, 260, 450, 260], fill=(30, 30, 30), width=2)
    d.line([50, 40, 50, 260], fill=(30, 30, 30), width=2)
    return _png(img)


def _photo() -> bytes:
    # a soft synthetic "photo" (many colours -> classified as photograph)
    img = Image.new("RGB", (420, 260))
    px = img.load()
    for y in range(260):
        for x in range(420):
            px[x, y] = (
                int(120 + 100 * math.sin(x / 40.0)),
                int(110 + 90 * math.cos(y / 35.0)),
                int(140 + 80 * math.sin((x + y) / 50.0)),
            )
    return _png(img)


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# --------------------------------------------------------------------------- #
def _text(page, pos, s, size, color, bold=False):
    page.insert_text(pos, s, fontsize=size, color=color,
                     fontname="hebo" if bold else "helv")


def build(path: str) -> str:
    doc = fitz.open()

    # ---- Page 1 -------------------------------------------------------- #
    p1 = doc.new_page()
    _text(p1, (60, 90), "Annual Accessibility & HR Policy Handbook", 22, BLACK, bold=True)  # H1
    _text(p1, (60, 130), "1. Welcome & Purpose", 16, BLACK, bold=True)                       # H2
    _text(p1, (60, 160), "This handbook explains employee rights and company policy.", 11, DARK)
    _text(p1, (60, 180), "Every team member should review it during onboarding.", 11, GREY)   # contrast
    _text(p1, (60, 200), "It is updated annually by the People Operations team.", 11, GREY)   # contrast
    _text(p1, (60, 220), "Questions may be directed to your manager or HR.", 11, GREY)        # contrast
    _text(p1, (60, 250), "Our commitment to accessibility is described below.", 11, DARK)
    p1.insert_image(fitz.Rect(60, 280, 260, 380), stream=_logo())
    _text(p1, (60, 392), "Figure 1: ClarityDesk corporate logo", 9, DARK)

    # ---- Page 2 -------------------------------------------------------- #
    p2 = doc.new_page()
    _text(p2, (60, 80), "2. Workplace Accommodations", 16, BLACK, bold=True)                  # H2
    _text(p2, (60, 110), "We provide reasonable accommodations on request.", 11, DARK)
    _text(p2, (60, 130), "Requests are handled confidentially within five days.", 11, GREY)   # contrast
    _text(p2, (60, 150), "The chart below shows recent request volume.", 11, GREY)            # contrast
    p2.insert_image(fitz.Rect(60, 180, 380, 380), stream=_chart())
    _text(p2, (60, 392), "Figure 2: 2024 quarterly accommodation requests by department", 9, DARK)

    # ---- Page 3 -------------------------------------------------------- #
    p3 = doc.new_page()
    _text(p3, (60, 80), "3. Reporting & Contacts", 16, BLACK, bold=True)                      # H2
    _text(p3, (60, 110), "Report concerns to the People Operations team.", 11, DARK)
    _text(p3, (60, 130), "You may also use the anonymous reporting line.", 11, GREY)          # contrast
    _text(p3, (60, 150), "Retaliation for good-faith reports is prohibited.", 11, GREY)       # contrast
    p3.insert_image(fitz.Rect(60, 180, 340, 360), stream=_photo())
    _text(p3, (60, 372), "Figure 3: HR team group photo", 9, DARK)

    # Deliberately DO NOT set: title, language, tags, bookmarks, alt text.
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))
    doc.close()
    return str(out)


def main() -> None:
    out = sys.argv[1] if len(sys.argv) > 1 else "demo/output/sample_inaccessible.pdf"
    path = build(out)
    print(f"Wrote inaccessible sample -> {path}")


if __name__ == "__main__":
    main()
