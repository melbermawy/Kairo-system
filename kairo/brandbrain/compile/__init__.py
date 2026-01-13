"""
BrandBrain Compile Orchestration.

PR-5: Compile Orchestration Skeleton.

This module provides:
- compile_brandbrain: Async compile kickoff
- get_compile_status: Status retrieval
- check_compile_gating: Pre-compile validation
- should_short_circuit: No-op detection
- compute_compile_input_hash: Deterministic hash for short-circuit

No LLM compilation in PR-5 (stub only).
"""

from kairo.brandbrain.compile.service import (
    CompileResult,
    check_compile_gating,
    compile_brandbrain,
    get_compile_status,
    should_short_circuit_compile,
)
from kairo.brandbrain.compile.hashing import compute_compile_input_hash

__all__ = [
    "compile_brandbrain",
    "get_compile_status",
    "check_compile_gating",
    "should_short_circuit_compile",
    "compute_compile_input_hash",
    "CompileResult",
]
