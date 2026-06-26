"""ClarityDesk - multi-agent WCAG/ADA accessibility auditor for SMB documents."""
from .orchestrator import Orchestrator
from .models import ComplianceReport, ScanResult, Violation
from .wcag import RULES, get_rule

__version__ = "0.1.0"
__all__ = [
    "Orchestrator", "ComplianceReport", "ScanResult", "Violation",
    "RULES", "get_rule", "__version__",
]
