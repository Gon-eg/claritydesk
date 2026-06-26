"""End-to-end demo: build an inaccessible PDF, audit it, and emit before/after.

Produces, under demo/output/:
  sample_inaccessible.pdf      the deliberately broken source
  sample_accessible.pdf        the remediated output
  report.json / report.md / report.html   the compliance report
  before_page1.png / after_page1.png       page renders for the README

This is the artifact set used for the 5-minute before/after video.
"""
from __future__ import annotations

import sys
from pathlib import Path

# allow running straight from the repo without installing
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

import fitz  # noqa: E402

from claritydesk import Orchestrator, report as R  # noqa: E402
from claritydesk.agents import ScanningAgent  # noqa: E402
from claritydesk.security import LocalDocument  # noqa: E402
from examples.generate_sample import build as build_sample  # noqa: E402

OUT = Path(__file__).resolve().parent / "output"


def _render(pdf: str, png: str, page: int = 0) -> None:
    doc = fitz.open(pdf)
    pix = doc[page].get_pixmap(matrix=fitz.Matrix(2, 2))
    pix.save(png)
    doc.close()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    src = str(OUT / "sample_inaccessible.pdf")
    dst = str(OUT / "sample_accessible.pdf")

    print("1) Building inaccessible sample…")
    build_sample(src)

    print("2) Auditing (scan -> remediate -> verify)…")
    rep = Orchestrator().audit(src, dst)

    print("3) Independent re-scan of the saved output (proof of fix)…")
    loc = LocalDocument.open(dst)
    re_scan = ScanningAgent().scan_path(dst, loc.sha256)

    (OUT / "report.json").write_text(R.to_json(rep))
    (OUT / "report.md").write_text(R.to_markdown(rep))
    (OUT / "report.html").write_text(R.to_html(rep))

    print("4) Rendering before/after page images…")
    _render(src, str(OUT / "before_page1.png"))
    _render(dst, str(OUT / "after_page1.png"))

    print("\n=== RESULT ===")
    print(f"Violations: {rep.before_count} -> {rep.after_count} "
          f"({'PASS' if rep.passed else 'FAIL'})")
    print(f"Independent re-scan of output: {re_scan.count} violations")
    print(f"Reports + renders written to {OUT}")


if __name__ == "__main__":
    main()
