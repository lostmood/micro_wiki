"""
Shadow evaluator for Day3.

v1 keeps manual approval, but this module predicts whether a patch would
be auto-approved under future criteria, and records reasoning for analytics.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class ShadowEvalResult:
    would_auto_apply: bool
    reason: str
    risk_level: str
    score: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ShadowEvaluator:
    """
    Rule-based shadow evaluator.
    """

    def evaluate_patch(
        self,
        operation: str,
        confidence: float,
        source_refs: list[str],
        affected_pages: list[str],
        diff_content: str,
    ) -> ShadowEvalResult:
        risk = self._risk_level(operation, affected_pages)
        score = self._score(confidence, len(source_refs), len(diff_content))

        if operation == "delete":
            return ShadowEvalResult(
                would_auto_apply=False,
                reason="delete_requires_manual_review",
                risk_level=risk,
                score=score,
            )

        if operation == "create" and confidence >= 0.95 and len(source_refs) >= 1:
            return ShadowEvalResult(
                would_auto_apply=True,
                reason="high_confidence_create",
                risk_level=risk,
                score=score,
            )

        if (
            operation == "update"
            and confidence >= 0.98
            and len(source_refs) >= 2
            and len(diff_content) <= 600
        ):
            return ShadowEvalResult(
                would_auto_apply=True,
                reason="high_confidence_small_update",
                risk_level=risk,
                score=score,
            )

        return ShadowEvalResult(
            would_auto_apply=False,
            reason="requires_human_review",
            risk_level=risk,
            score=score,
        )

    def _risk_level(self, operation: str, affected_pages: list[str]) -> str:
        if operation == "delete":
            return "high"
        if operation == "update" and len(affected_pages) > 3:
            return "high"
        if operation == "update":
            return "medium"
        return "low"

    def _score(self, confidence: float, source_ref_count: int, diff_len: int) -> float:
        # Simple bounded heuristic score for analytics/debug.
        normalized_diff = 1.0 if diff_len <= 120 else max(0.0, 1.0 - (diff_len - 120) / 1200)
        score = 0.65 * confidence + 0.2 * min(1.0, source_ref_count / 3.0) + 0.15 * normalized_diff
        return round(max(0.0, min(1.0, score)), 4)
