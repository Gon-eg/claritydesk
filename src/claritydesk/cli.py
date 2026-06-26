"""ClarityDesk command-line interface.

  claritydesk scan       <pdf>                 # list violations
  claritydesk audit      <pdf> [-o out.pdf]    # fix + verify, write report
  claritydesk rules                            # show the rule catalog
  claritydesk serve                            # start the MCP server
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import report as R
from .orchestrator import Orchestrator
from .wcag import RULES


def _cmd_scan(args: argparse.Namespace) -> int:
    rep = Orchestrator().scan_only(args.pdf)
    scan = rep.before
    print(f"{scan.source}")
    print(f"{scan.pages} pages · {scan.count} violations\n")
    for v in scan.violations:
        loc = "doc" if v.page == 0 else f"p{v.page}"
        print(f"  [{v.sc:>5} {v.level}] ({loc}) {v.message}")
    if args.json:
        Path(args.json).write_text(R.to_json(rep))
        print(f"\nWrote {args.json}")
    return 0 if scan.count == 0 else 1


def _cmd_audit(args: argparse.Namespace) -> int:
    orc = Orchestrator(language=args.lang)
    rep = orc.audit(args.pdf, args.output)
    print(f"Violations: {rep.before_count} -> {rep.after_count} "
          f"({'PASS' if rep.passed else 'FAIL'})")
    print(f"Accessible copy: {rep.output}")
    if args.report:
        out = Path(args.report)
        fmt = out.suffix.lstrip(".").lower()
        text = {"json": R.to_json, "md": R.to_markdown,
                "markdown": R.to_markdown, "html": R.to_html}.get(fmt, R.to_json)(rep)
        out.write_text(text)
        print(f"Report: {out}")
    return 0 if rep.passed else 2


def _cmd_rules(_args: argparse.Namespace) -> int:
    for r in RULES.values():
        print(f"{r.sc:>6} {r.level:<2} {r.id:<15} {r.name}")
        print(f"        {r.summary}")
    return 0


def _cmd_serve(_args: argparse.Namespace) -> int:
    try:
        from .mcp_server import main as serve_main
    except SystemExit as e:
        print(e, file=sys.stderr)
        return 1
    serve_main()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="claritydesk",
                                description="Multi-agent WCAG/ADA document auditor.")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("scan", help="List WCAG violations (read-only).")
    s.add_argument("pdf")
    s.add_argument("--json", help="Also write the scan result as JSON to this path.")
    s.set_defaults(func=_cmd_scan)

    a = sub.add_parser("audit", help="Scan, remediate and verify a PDF.")
    a.add_argument("pdf")
    a.add_argument("-o", "--output", help="Output accessible PDF path.")
    a.add_argument("--lang", default="en-US", help="Document language (default en-US).")
    a.add_argument("--report", help="Write report to .json/.md/.html by extension.")
    a.set_defaults(func=_cmd_audit)

    r = sub.add_parser("rules", help="Show the implemented WCAG rule catalog.")
    r.set_defaults(func=_cmd_rules)

    sv = sub.add_parser("serve", help="Run the MCP compliance server (stdio).")
    sv.set_defaults(func=_cmd_serve)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
