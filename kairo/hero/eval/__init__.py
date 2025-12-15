"""
Kairo Eval Harness.

PR-10: Offline Eval Harness + Fixtures.

This package provides the offline evaluation harness for measuring
hero loop (F1/F2) quality and tracking regressions.

Per docs/eval/evalHarness.md and PR-map-and-standards §PR-10.
"""

from kairo.hero.eval.f1_f2_hero_loop import (
    EvalCaseResult,
    EvalResult,
    HeroEvalStageStatus,
    run_hero_loop_eval,
)

__all__ = [
    "run_hero_loop_eval",
    "EvalResult",
    "EvalCaseResult",
    "HeroEvalStageStatus",
]
