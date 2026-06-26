"""ClarityDesk MCP server.

Exposes the audit pipeline as Model Context Protocol tools so other internal
tools (a CMS, a help-desk bot, a CI check) can query a document's compliance
report programmatically.

Tools:
  list_wcag_rules()                      -> the rule catalog ClarityDesk checks
  scan_document(path)                    -> violations only (no changes)
  audit_document(path, output=None)      -> scan + remediate + verify, returns report
  get_compliance_report(path)            -> cached summary suitable for a CMS badge

Run:
  pip install -r requirements-mcp.txt
  python -m claritydesk.mcp_server          # stdio transport

All processing happens inside the local security sandbox; document bytes never
leave the host (the cloud vision provider is opt-in and must be allow-listed).
"""
from __future__ import annotations

import json
from typing import Optional

from .orchestrator import Orchestrator
from .report import to_markdown
from .wcag import RULES

try:
    from mcp.server.fastmcp import FastMCP
except Exception as exc:  # pragma: no cover
    raise SystemExit(
        "The MCP SDK is not installed. Run: pip install -r requirements-mcp.txt"
    ) from exc

mcp = FastMCP("claritydesk")

# tiny in-process cache so a CMS can poll a report without re-running each time
_CACHE: dict[str, dict] = {}


@mcp.tool()
def list_wcag_rules() -> str:
    """List the WCAG/PDF-UA rules ClarityDesk checks and how it fixes each."""
    out = [{
        "id": r.id, "sc": r.sc, "name": r.name, "level": r.level,
        "summary": r.summary, "how_to_fix": r.how_to_fix, "wcag_url": r.wcag_url,
    } for r in RULES.values()]
    return json.dumps(out, indent=2)


@mcp.tool()
def scan_document(path: str) -> str:
    """Scan a local PDF and return its WCAG violations (read-only, no changes)."""
    rep = Orchestrator().scan_only(path)
    return json.dumps(rep.before.to_dict(), indent=2)


@mcp.tool()
def audit_document(path: str, output: Optional[str] = None) -> str:
    """Scan, remediate and verify a local PDF. Returns the full compliance report.

    Writes an accessible copy next to the source (or to `output`).
    """
    rep = Orchestrator().audit(path, output)
    _CACHE[path] = rep.to_dict()
    return json.dumps(rep.to_dict(), indent=2)


@mcp.tool()
def get_compliance_report(path: str, refresh: bool = False) -> str:
    """Return a compact compliance summary for `path` (cached after first audit).

    Designed for a CMS to show an accessibility badge: pass/fail, counts, and the
    per-rule breakdown. Pass refresh=True to force a re-audit.
    """
    if refresh or path not in _CACHE:
        _CACHE[path] = Orchestrator().audit(path).to_dict()
    r = _CACHE[path]
    summary = {
        "source": r["source"],
        "passed": r["passed"],
        "before_count": r["before_count"],
        "after_count": r["after_count"],
        "resolved_count": r["resolved_count"],
        "before_by_rule": r["before"]["by_rule"],
        "after_by_rule": r["after"]["by_rule"],
        "output": r["output"],
    }
    return json.dumps(summary, indent=2)


@mcp.tool()
def compliance_report_markdown(path: str) -> str:
    """Return a human-readable Markdown compliance report for a local PDF."""
    rep = Orchestrator().audit(path)
    return to_markdown(rep)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
