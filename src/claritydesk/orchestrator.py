"""Orchestrator - the multi-agent plan -> act -> verify control loop.

Wires the Scanning, Remediation and Verification agents together and runs the
whole pipeline inside the security sandbox (`network_guard`) so a confidential
document's bytes never leave the local session unless cloud vision is explicitly
enabled and allow-listed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import fitz

from .agents import RemediationAgent, ScanningAgent, VerificationAgent
from .agents.scanning_agent import scan_document
from .alt_text import AltTextProvider
from .models import ComplianceReport, RemediationAction, VerificationItem
from .security import LocalDocument, network_guard


class Orchestrator:
    def __init__(self,
                 alt_provider: Optional[AltTextProvider] = None,
                 language: str = "en-US",
                 max_passes: int = 2,
                 allow_hosts: Optional[list[str]] = None):
        self.scanner = ScanningAgent()
        self.remediator = RemediationAgent(alt_provider=alt_provider, language=language)
        self.verifier = VerificationAgent()
        self.max_passes = max(1, max_passes)
        # If a cloud vision provider is in use it must be explicitly allow-listed.
        if allow_hosts is None and getattr(self.remediator.alt_provider, "name", "") == "vision":
            allow_hosts = ["api.openai.com"]
        self.allow_hosts = allow_hosts

    # ------------------------------------------------------------------ #
    def scan_only(self, path: str) -> ComplianceReport:
        local = LocalDocument.open(path)
        with network_guard(self.allow_hosts):
            doc = fitz.open(str(local.path))
            try:
                before = scan_document(doc, source=str(local.path), sha256=local.sha256)
            finally:
                doc.close()
        return ComplianceReport(source=str(local.path), output=None,
                                before=before, after=before, actions=[],
                                verification=[])

    def audit(self, path: str, output: Optional[str] = None) -> ComplianceReport:
        """Full pipeline: scan -> remediate -> verify, returning a report."""
        local = LocalDocument.open(path)
        out_path = Path(output) if output else \
            local.path.with_name(local.path.stem + ".accessible.pdf")

        with network_guard(self.allow_hosts):
            doc = fitz.open(str(local.path))
            try:
                before = scan_document(doc, source=str(local.path),
                                       sha256=local.sha256)

                all_actions: list[RemediationAction] = []
                verification: list[VerificationItem] = []
                after = before
                current_scan = before

                for _ in range(self.max_passes):
                    actions = self.remediator.remediate(doc, current_scan)
                    all_actions.extend(actions)
                    after, verification = self.verifier.verify(
                        doc, before, source=str(out_path), sha256=local.sha256)
                    if after.count == 0:
                        break
                    # Feed residual violations back into the next pass.
                    current_scan = after

                doc.save(str(out_path), garbage=4, deflate=True)
            finally:
                doc.close()

        return ComplianceReport(
            source=str(local.path), output=str(out_path),
            before=before, after=after,
            actions=all_actions, verification=verification)
