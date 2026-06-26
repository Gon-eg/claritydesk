# Architecture

ClarityDesk is a three-agent pipeline coordinated by an Orchestrator that runs
the classic **plan → act → verify** control loop. Every stage operates on a
shared, typed data model (`src/claritydesk/models.py`) so agents never re-parse
each other's work.

```
LocalDocument ──▶ ScanResult ──▶ RemediationAction[] ──▶ VerificationItem[]
   (security)      (plan)            (act)                   (verify)
                                                              │
                                                       ComplianceReport
```

## Agents

### 1. Scanning Agent (`agents/scanning_agent.py`) — *plan*
Opens the PDF with PyMuPDF and runs every implemented check. It emits a
`ScanResult` whose `Violation`s carry **everything the fixer needs**: bounding
boxes, colours, font sizes, image xrefs, and the nearest caption/heading for each
image. The Scanning Agent decides *what* is wrong; it never mutates the document.

Heading detection is style-based (a line whose largest span is ≥ 15 pt, or bold
≥ 13 pt). Contrast uses the WCAG relative-luminance formula against a best-effort
page background (defaults to white).

### 2. Remediation Agent (`agents/remediation_agent.py`) — *act*
Consumes the `ScanResult` and mutates the document in place:

- **doc-title / doc-language / tagged-pdf** — catalog-level fixes (metadata
  title + `DisplayDocTitle`, `/Lang`, `/MarkInfo /Marked true`, `StructTreeRoot`).
- **heading-tagged** — adds `H1`/`H2` structure elements carrying the heading text.
- **image-alt** — calls a pluggable `AltTextProvider` to write **context-aware**
  alt text (caption + nearest heading + pixel analysis), then attaches a
  `Figure`/`Alt` structure element per image.
- **bookmarks** — builds a document outline from the detected headings.
- **contrast** — groups violations per page, redacts the offending text runs, and
  re-inserts them darkened to an AAA-level margin (≈ 7:1) so the fix is
  comfortably legible, not borderline.

Every change is recorded as a `RemediationAction` (including the generated alt
text / title), so the report is fully auditable.

### 3. Verification Agent (`agents/verification_agent.py`) — *verify*
Re-runs the **exact same** `scan_document` function on the remediated document
and matches each original violation:

- document-level rules pass when no residual violation of that rule remains;
- per-element rules (image-alt, heading-tagged, contrast) match by target.

It also surfaces any **newly introduced** violations (regression guard). The
audit only "passes" when the after-count is zero.

## Orchestrator (`orchestrator.py`)
Wraps the loop in the security sandbox and supports multiple passes: residual
violations from `verify` are fed back into `act`. In practice the sample
converges in a single pass (18 → 0).

## MCP Server (`mcp_server.py`)
A FastMCP server exposing the pipeline as MCP tools so a CMS, help-desk bot, or
CI gate can request a compliance report. `get_compliance_report` returns a
compact, cacheable summary suitable for an accessibility badge.

## PDF primitives (`pdf_utils.py`)
All low-level PyMuPDF logic lives here, free of agent semantics:
contrast math, text-line extraction, image listing, catalog reads, and a small
structure-tree reader/writer built on `xref_get_key` / `xref_set_key` /
`update_object`.

## Scope & limitations (read this)

ClarityDesk implements a **practical, high-impact subset** of WCAG 2.1 / PDF-UA.
It is intentionally honest about what it does:

- The structure tree it builds attaches **roles + alt text + heading text** that
  the Verification Agent reads back. It does **not** yet wire each structure
  element to page content via **MCID marked-content** operators, which full
  PDF/UA conformance requires. This is the top roadmap item.
- Contrast remediation recolours text via redaction + re-insertion using the
  Helvetica base font; documents with unusual embedded fonts may shift glyph
  metrics slightly. It is best suited to text-based business documents.
- Background detection is best-effort (full-page fill or white default).
- Reading order is preserved from the source; it is not re-derived.

These boundaries are deliberate: the goal is a *trustworthy, verifiable* drop in
real violations for typical SMB documents, with a clear path to full PDF/UA.

## Extending

- **New rule:** add it to `wcag/rules.py`, emit a `Violation` in
  `scan_document`, handle it in `RemediationAgent.remediate`, and the Verification
  Agent picks it up automatically.
- **Better alt text:** implement the `AltTextProvider` protocol in `alt_text.py`.
