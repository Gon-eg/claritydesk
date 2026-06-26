"""Render a ComplianceReport as JSON, Markdown, or a self-contained HTML page."""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone

from .models import ComplianceReport
from .wcag import get_rule


def to_json(report: ComplianceReport, indent: int = 2) -> str:
    return json.dumps(report.to_dict(), indent=indent)


def _ts(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def to_markdown(report: ComplianceReport) -> str:
    r = report
    lines = [
        f"# ClarityDesk Compliance Report",
        "",
        f"**Source:** `{r.source}`  ",
        f"**Output:** `{r.output or '-'}`  ",
        f"**Generated:** {_ts(r.generated_at)}  ",
        f"**Document hash:** `{r.before.sha256[:16]}…`",
        "",
        f"## Result: {'✅ PASS (0 violations)' if r.passed else f'⚠️ {r.after_count} remaining'}",
        "",
        f"- Violations before: **{r.before_count}**",
        f"- Violations after: **{r.after_count}**",
        f"- Resolved: **{r.resolved_count} / {r.before_count}**",
        "",
        "## Violations by rule",
        "",
        "| WCAG SC | Level | Rule | Before | After |",
        "|---|---|---|---:|---:|",
    ]
    before_by = r.before.by_rule()
    after_by = r.after.by_rule()
    for rule_id in sorted(set(before_by) | set(after_by)):
        rule = get_rule(rule_id)
        lines.append(
            f"| {rule.sc} | {rule.level} | {rule.name} | "
            f"{before_by.get(rule_id, 0)} | {after_by.get(rule_id, 0)} |")

    lines += ["", "## Fixes applied", ""]
    if not r.actions:
        lines.append("_No fixes applied._")
    for a in r.actions:
        extra = ""
        if "alt_text" in a.generated:
            extra = f' → alt: "{a.generated["alt_text"]}"'
        elif "title" in a.generated:
            extra = f' → "{a.generated["title"]}"'
        elif "text" in a.generated:
            extra = f' → "{a.generated["text"]}"'
        lines.append(f"- **{get_rule(a.rule_id).sc}** (p{a.page}) {a.description}{extra}")

    lines += ["", "## Verification", ""]
    for v in r.verification:
        mark = "✅" if v.resolved else "❌"
        lines.append(f"- {mark} {get_rule(v.rule_id).sc} — {v.target or 'document'} — {v.note}")
    return "\n".join(lines)


def to_html(report: ComplianceReport) -> str:
    r = report
    before_by = r.before.by_rule()
    after_by = r.after.by_rule()
    rows = ""
    for rule_id in sorted(set(before_by) | set(after_by)):
        rule = get_rule(rule_id)
        b = before_by.get(rule_id, 0)
        a = after_by.get(rule_id, 0)
        cls = "ok" if a == 0 else "warn"
        rows += (
            f"<tr><td><a href='{html.escape(rule.wcag_url)}' target='_blank'>"
            f"{rule.sc}</a></td><td>{rule.level}</td><td>{html.escape(rule.name)}</td>"
            f"<td class='num'>{b}</td><td class='num {cls}'>{a}</td></tr>")

    fixes = ""
    for act in r.actions:
        detail = ""
        if "alt_text" in act.generated:
            detail = f"<span class='gen'>alt: “{html.escape(act.generated['alt_text'])}”</span>"
        elif "title" in act.generated:
            detail = f"<span class='gen'>“{html.escape(act.generated['title'])}”</span>"
        elif "text" in act.generated:
            detail = f"<span class='gen'>“{html.escape(str(act.generated['text']))}”</span>"
        fixes += (f"<li><b>{get_rule(act.rule_id).sc}</b> "
                  f"<small>p{act.page}</small> {html.escape(act.description)} {detail}</li>")

    status = "PASS" if r.passed else f"{r.after_count} REMAINING"
    status_cls = "pass" if r.passed else "fail"
    pct = 0 if not r.before_count else round(100 * r.resolved_count / r.before_count)

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ClarityDesk Compliance Report</title>
<style>
 :root{{--bg:#0b1220;--card:#121b2e;--ink:#e8eef9;--mut:#9fb0cc;--line:#243349;
        --ok:#2ecc71;--warn:#e67e22;--bad:#e74c3c;--accent:#4aa3ff;}}
 *{{box-sizing:border-box}}
 body{{margin:0;font:15px/1.5 system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--ink)}}
 .wrap{{max-width:920px;margin:0 auto;padding:32px 20px}}
 h1{{font-size:24px;margin:0 0 4px}} .sub{{color:var(--mut);font-size:13px;word-break:break-all}}
 .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin:22px 0}}
 .card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px}}
 .card .big{{font-size:34px;font-weight:700}}
 .card.before .big{{color:var(--bad)}} .card.after .big{{color:var(--ok)}}
 .label{{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.06em}}
 .status{{display:inline-block;padding:6px 14px;border-radius:999px;font-weight:700}}
 .status.pass{{background:rgba(46,204,113,.15);color:var(--ok);border:1px solid var(--ok)}}
 .status.fail{{background:rgba(231,76,60,.15);color:var(--bad);border:1px solid var(--bad)}}
 table{{width:100%;border-collapse:collapse;margin-top:8px}}
 th,td{{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line)}}
 th{{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.05em}}
 td.num{{text-align:right;font-variant-numeric:tabular-nums;font-weight:600}}
 td.num.ok{{color:var(--ok)}} td.num.warn{{color:var(--warn)}}
 a{{color:var(--accent)}}
 .bar{{height:10px;border-radius:999px;background:#22304a;overflow:hidden;margin-top:10px}}
 .bar>i{{display:block;height:100%;background:linear-gradient(90deg,#2ecc71,#4aa3ff);width:{pct}%}}
 ul.fixes{{list-style:none;padding:0;margin:8px 0}}
 ul.fixes li{{padding:8px 0;border-bottom:1px solid var(--line)}}
 .gen{{color:var(--accent)}} small{{color:var(--mut)}}
 h2{{margin-top:30px;font-size:17px}}
</style></head><body><div class="wrap">
 <h1>ClarityDesk Compliance Report</h1>
 <div class="sub">Source: {html.escape(r.source)}<br>
   Document hash: {r.before.sha256[:16]}… · Generated {_ts(r.generated_at)}</div>

 <div class="grid">
   <div class="card before"><div class="label">Violations before</div><div class="big">{r.before_count}</div></div>
   <div class="card after"><div class="label">Violations after</div><div class="big">{r.after_count}</div></div>
   <div class="card"><div class="label">Status</div>
     <div style="margin-top:10px"><span class="status {status_cls}">{status}</span></div>
     <div class="bar"><i></i></div>
     <div class="label" style="margin-top:8px">{r.resolved_count}/{r.before_count} resolved</div></div>
 </div>

 <h2>Violations by WCAG rule</h2>
 <table><thead><tr><th>SC</th><th>Level</th><th>Rule</th><th>Before</th><th>After</th></tr></thead>
 <tbody>{rows}</tbody></table>

 <h2>Fixes applied ({len(r.actions)})</h2>
 <ul class="fixes">{fixes or '<li>No fixes applied.</li>'}</ul>
</div></body></html>"""
