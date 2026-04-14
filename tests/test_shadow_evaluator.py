"""
Tests for ShadowEvaluator (Day3).
"""

from wiki_engine.shadow_evaluator import ShadowEvaluator


def test_high_confidence_create_can_auto_apply():
    evaluator = ShadowEvaluator()
    result = evaluator.evaluate_patch(
        operation="create",
        confidence=0.97,
        source_refs=["paper-a"],
        affected_pages=["page-a"],
        diff_content="new content",
    )
    assert result.would_auto_apply
    assert result.reason == "high_confidence_create"
    assert result.risk_level == "low"


def test_delete_always_requires_manual_review():
    evaluator = ShadowEvaluator()
    result = evaluator.evaluate_patch(
        operation="delete",
        confidence=1.0,
        source_refs=["paper-a", "paper-b"],
        affected_pages=["page-a"],
        diff_content="remove",
    )
    assert not result.would_auto_apply
    assert result.reason == "delete_requires_manual_review"
    assert result.risk_level == "high"


def test_update_auto_apply_rule():
    evaluator = ShadowEvaluator()
    result = evaluator.evaluate_patch(
        operation="update",
        confidence=0.99,
        source_refs=["paper-a", "paper-b"],
        affected_pages=["page-a"],
        diff_content="small edit",
    )
    assert result.would_auto_apply
    assert result.reason == "high_confidence_small_update"
    assert result.risk_level == "medium"


def test_low_confidence_update_stays_manual():
    evaluator = ShadowEvaluator()
    result = evaluator.evaluate_patch(
        operation="update",
        confidence=0.70,
        source_refs=["paper-a"],
        affected_pages=["page-a"],
        diff_content="edit",
    )
    assert not result.would_auto_apply
    assert result.reason == "requires_human_review"


if __name__ == "__main__":
    test_high_confidence_create_can_auto_apply()
    test_delete_always_requires_manual_review()
    test_update_auto_apply_rule()
    test_low_confidence_update_stays_manual()
    print("\n✓ All shadow evaluator tests passed")
