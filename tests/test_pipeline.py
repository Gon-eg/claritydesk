"""End-to-end and unit tests for the ClarityDesk pipeline."""
from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from claritydesk import Orchestrator, pdf_utils as pu  # noqa: E402
from claritydesk.agents import ScanningAgent  # noqa: E402
from claritydesk.security import LocalDocument, network_guard, EgressBlocked  # noqa: E402
from examples.generate_sample import build as build_sample  # noqa: E402


@pytest.fixture()
def sample(tmp_path: Path) -> str:
    return build_sample(str(tmp_path / "sample.pdf"))


def test_sample_has_exactly_18_violations(sample):
    loc = LocalDocument.open(sample)
    scan = ScanningAgent().scan_path(sample, loc.sha256)
    assert scan.count == 18
    assert scan.by_rule() == {
        "doc-title": 1, "doc-language": 1, "tagged-pdf": 1, "bookmarks": 1,
        "contrast": 7, "heading-tagged": 4, "image-alt": 3,
    }


def test_audit_resolves_all_violations(sample, tmp_path):
    out = str(tmp_path / "fixed.pdf")
    rep = Orchestrator().audit(sample, out)
    assert rep.before_count == 18
    assert rep.after_count == 0
    assert rep.passed is True
    assert rep.resolved_count == 18
    assert all(v.resolved for v in rep.verification)


def test_independent_rescan_of_output_is_clean(sample, tmp_path):
    out = str(tmp_path / "fixed.pdf")
    Orchestrator().audit(sample, out)
    loc = LocalDocument.open(out)
    rescan = ScanningAgent().scan_path(out, loc.sha256)
    assert rescan.count == 0


def test_remediated_pdf_is_tagged_and_localized(sample, tmp_path):
    out = str(tmp_path / "fixed.pdf")
    Orchestrator().audit(sample, out)
    doc = fitz.open(out)
    try:
        assert pu.is_marked(doc)
        assert pu.struct_tree_root(doc) is not None
        assert pu.get_language(doc) == "en-US"
        assert pu.has_title(doc) and pu.display_doc_title(doc)
        assert len(pu.figures_with_alt(doc)) == 3
        assert len(pu.heading_elements(doc)) == 4
        assert len(doc.get_toc()) >= 3
    finally:
        doc.close()


def test_alt_text_is_context_aware(sample, tmp_path):
    out = str(tmp_path / "fixed.pdf")
    rep = Orchestrator().audit(sample, out)
    alts = [a.generated.get("alt_text", "") for a in rep.actions if a.rule_id == "image-alt"]
    assert len(alts) == 3
    # alt text should reflect the figure captions, not a generic placeholder
    assert any("logo" in a.lower() for a in alts)
    assert any("quarterly" in a.lower() or "request" in a.lower() for a in alts)


def test_contrast_meets_minimum_after_fix(sample, tmp_path):
    out = str(tmp_path / "fixed.pdf")
    Orchestrator().audit(sample, out)
    doc = fitz.open(out)
    try:
        for pno in range(doc.page_count):
            page = doc[pno]
            bg = pu.page_background(page)
            for ln in pu.iter_text_lines(page, pno + 1):
                need = pu.CONTRAST_MIN_LARGE if ln.is_large_text else pu.CONTRAST_MIN_NORMAL
                assert pu.contrast_ratio(ln.color, bg) + 1e-6 >= need
    finally:
        doc.close()


def test_contrast_math_known_values():
    assert round(pu.contrast_ratio((0, 0, 0), (1, 1, 1)), 1) == 21.0
    assert pu.contrast_ratio((1, 1, 1), (1, 1, 1)) == 1.0


def test_network_guard_blocks_egress_and_restores():
    import socket
    original = socket.socket.connect
    with network_guard():
        assert socket.socket.connect is not original  # guard installed
        with pytest.raises(EgressBlocked):
            socket.create_connection(("93.184.216.34", 80), timeout=1)
    # guard must be fully removed on exit
    assert socket.socket.connect is original


def test_network_guard_allowlist():
    import socket
    with network_guard(allow_hosts=["127.0.0.1"]):
        # loopback is always allowed; connecting to a closed port raises ConnectionRefused
        s = socket.socket()
        s.settimeout(0.2)
        try:
            s.connect(("127.0.0.1", 1))
        except EgressBlocked:
            pytest.fail("loopback should not be blocked")
        except OSError:
            pass
        finally:
            s.close()
