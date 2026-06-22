"""Конвейер исполнения: TODO → нано-промпт → код → дерево файлов → аудит → доводка."""

from .assembler import assemble, render_tree
from .auditor import apply_audit, build_audit_input, parse_audit, run_audit
from .context import assemble_context
from .orchestrator import Orchestrator, ReviewDecision
from .verify import VerifyResult, format_errors, run_verification

__all__ = [
    "Orchestrator", "ReviewDecision",
    "assemble", "render_tree", "assemble_context",
    "run_audit", "apply_audit", "parse_audit", "build_audit_input",
    "run_verification", "format_errors", "VerifyResult",
]
