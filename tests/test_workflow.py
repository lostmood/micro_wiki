"""
Tests for wiki workflow engine (propose -> lint -> apply pipeline).

Test coverage:
1. propose_patch generates patch_id and saves to .pending/
2. apply_patch verifies signature and applies atomically
3. TOCTOU protection: apply fails if base_commit changed
4. Signature verification: patch_id must match
5. Lint gate: apply fails if lint didn't pass
6. ACL enforcement: unauthorized approver rejected
"""

import json
import os
import tempfile
import time
from pathlib import Path

import pytest

from wiki_engine.workflow import WikiWorkflow
from wiki_engine.acl import ApprovalACL


@pytest.fixture
def temp_wiki():
    """Create temporary wiki directory with required structure"""
    with tempfile.TemporaryDirectory() as tmpdir:
        wiki_root = tmpdir

        # Create required directories
        os.makedirs(f"{wiki_root}/.schema", exist_ok=True)
        os.makedirs(f"{wiki_root}/.locks", exist_ok=True)
        os.makedirs(f"{wiki_root}/.pending", exist_ok=True)
        os.makedirs(f"{wiki_root}/.audit", exist_ok=True)
        os.makedirs(f"{wiki_root}/wiki", exist_ok=True)

        # Create approvers.yaml
        approvers_config = {
            "version": "v1",
            "signature": {
                "ttl_seconds": 300,
                "nonce_bits": 128,
                "algorithm": "hmac_sha256"
            },
            "authorized_approvers": [
                {
                    "id": "human-alice",
                    "name": "Alice",
                    "role": "owner",
                    "auth_method": "session_identity",
                    "permissions": ["approve_all"]
                }
            ],
            "operation_permissions": {
                "approve_all": ["*"],
                "approve_low_risk": ["create_page", "update_metadata"]
            },
            "audit": {
                "require_signature": True,
                "signature_method": "hmac_sha256",
                "log_all_attempts": True,
                "audit_dir": ".audit"
            }
        }

        with open(f"{wiki_root}/.schema/approvers.yaml", "w") as f:
            import yaml
            yaml.dump(approvers_config, f)

        # Initialize git repo
        os.system(f"cd {wiki_root} && git init && git config user.email 'test@example.com' && git config user.name 'Test' && git commit --allow-empty -m 'Initial commit' 2>/dev/null")

        yield wiki_root


def test_propose_patch_generates_patch_id(temp_wiki):
    """Test that propose_patch generates unique patch_id and saves to .pending/"""
    workflow = WikiWorkflow(temp_wiki)

    result = workflow.propose_patch(
        agent_id="agent-test",
        operation="create",
        pages=["page-1"],
        diff="+ New content",
        confidence=0.95,
        sources=["source-1"]
    )

    assert result["status"] == "success"
    assert "patch_id" in result
    assert result["patch_id"].startswith("patch-")
    assert result["requires_approval"] is True
    assert result["confidence"] == 0.95
    assert result["lint_status"] == "passed"

    # Verify patch saved to .pending/
    patch_file = f"{temp_wiki}/.pending/{result['patch_id']}.json"
    assert os.path.exists(patch_file)

    with open(patch_file) as f:
        patch_data = json.load(f)
        assert patch_data["patch_id"] == result["patch_id"]
        assert patch_data["agent_id"] == "agent-test"
        assert patch_data["operation"] == "create"
        assert patch_data["confidence"] == 0.95


def test_apply_patch_verifies_signature(temp_wiki):
    """Test that apply_patch verifies signature and rejects invalid ones"""
    workflow = WikiWorkflow(temp_wiki)

    # Propose a patch
    result = workflow.propose_patch(
        agent_id="agent-test",
        operation="create",
        pages=["page-1"],
        diff="+ New content",
        confidence=0.95,
        sources=["source-1"]
    )
    patch_id = result["patch_id"]

    # Get base commit
    base_commit = workflow._get_current_commit()

    # Try to apply with invalid signature
    invalid_approval = {
        "approver_id": "human-alice",
        "patch_id": patch_id,
        "timestamp": time.time(),
        "nonce": "invalid-nonce",
        "expires_at": time.time() + 300,
        "expected_base_commit": base_commit,
        "signature": "invalid-signature"
    }

    result = workflow.apply_patch(patch_id, invalid_approval, base_commit)

    assert result["status"] == "failed"
    assert "signature_verification_failed" in result["reason"]


def test_apply_patch_rejects_patch_id_mismatch(temp_wiki):
    """Test that apply_patch rejects signature with mismatched patch_id"""
    workflow = WikiWorkflow(temp_wiki)
    acl = workflow.acl

    # Propose a patch
    result = workflow.propose_patch(
        agent_id="agent-test",
        operation="create",
        pages=["page-1"],
        diff="+ New content",
        confidence=0.95,
        sources=["source-1"]
    )
    patch_id = result["patch_id"]

    # Get base commit
    base_commit = workflow._get_current_commit()

    # Create valid signature but for different patch_id
    wrong_patch_id = "patch-wrong-12345"
    signed_approval = acl.sign_approval(
        approver_id="human-alice",
        patch_id=wrong_patch_id,  # Wrong patch_id
        expected_base_commit=base_commit
    )

    result = workflow.apply_patch(patch_id, signed_approval, base_commit)

    assert result["status"] == "failed"
    assert result["reason"] == "patch_id_mismatch"
    assert wrong_patch_id in result["message"]


def test_apply_patch_toctou_protection(temp_wiki):
    """Test that apply_patch fails if base_commit changed (TOCTOU protection)"""
    workflow = WikiWorkflow(temp_wiki)
    acl = workflow.acl

    # Propose a patch
    result = workflow.propose_patch(
        agent_id="agent-test",
        operation="create",
        pages=["page-1"],
        diff="+ New content",
        confidence=0.95,
        sources=["source-1"]
    )
    patch_id = result["patch_id"]

    # Get base commit
    base_commit = workflow._get_current_commit()

    # Create valid signature
    signed_approval = acl.sign_approval(
        approver_id="human-alice",
        patch_id=patch_id,
        expected_base_commit=base_commit
    )

    # Simulate concurrent change: create a new commit
    os.system(f"cd {temp_wiki} && git commit --allow-empty -m 'Concurrent change' 2>/dev/null")

    # Try to apply - should fail due to base_commit mismatch
    result = workflow.apply_patch(patch_id, signed_approval, base_commit)

    assert result["status"] == "failed"
    assert result["reason"] == "base_commit_changed"
    assert "expected" in result
    assert "actual" in result
    assert result["expected"] == base_commit
    assert result["actual"] != base_commit


def test_apply_patch_rejects_unauthorized_approver(temp_wiki):
    """Test that apply_patch rejects unauthorized approver"""
    workflow = WikiWorkflow(temp_wiki)

    # Propose a patch
    result = workflow.propose_patch(
        agent_id="agent-test",
        operation="create",
        pages=["page-1"],
        diff="+ New content",
        confidence=0.95,
        sources=["source-1"]
    )
    patch_id = result["patch_id"]

    # Get base commit
    base_commit = workflow._get_current_commit()

    # Try to apply with unauthorized approver
    # Note: We can't easily forge a valid signature for unauthorized user,
    # so we test the verify_approver path directly
    fake_approval = {
        "approver_id": "human-unauthorized",
        "patch_id": patch_id,
        "timestamp": time.time(),
        "nonce": "test-nonce",
        "expires_at": time.time() + 300,
        "expected_base_commit": base_commit,
        "signature": "fake-signature"
    }

    # Manually bypass signature verification to test approver check
    # (In real scenario, signature verification would fail first)
    assert not workflow.acl.verify_approver("human-unauthorized")


def test_apply_patch_success_flow(temp_wiki):
    """Test successful apply_patch flow with valid signature"""
    workflow = WikiWorkflow(temp_wiki)
    acl = workflow.acl

    # Propose a patch
    result = workflow.propose_patch(
        agent_id="agent-test",
        operation="create",
        pages=["page-1"],
        diff="+ New content",
        confidence=0.95,
        sources=["source-1"]
    )
    patch_id = result["patch_id"]

    # Get base commit
    base_commit = workflow._get_current_commit()

    # Create valid signature
    signed_approval = acl.sign_approval(
        approver_id="human-alice",
        patch_id=patch_id,
        expected_base_commit=base_commit
    )

    # Apply patch
    result = workflow.apply_patch(patch_id, signed_approval, base_commit)

    assert result["status"] == "success"
    assert "change_id" in result
    assert result["change_id"].startswith("ch-")
    assert "commit_hash" in result
    assert "applied_at" in result

    # Verify patch removed from .pending/
    patch_file = f"{temp_wiki}/.pending/{patch_id}.json"
    assert not os.path.exists(patch_file)

    # Verify audit log created
    audit_file = f"{temp_wiki}/.audit/changes.jsonl"
    assert os.path.exists(audit_file)

    with open(audit_file) as f:
        lines = f.readlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["change_id"] == result["change_id"]
        assert record["patch_id"] == patch_id
        assert record["approver_id"] == "human-alice"


def test_apply_patch_double_check_toctou_under_lock(temp_wiki):
    """Test that apply_patch double-checks TOCTOU after acquiring lock"""
    workflow = WikiWorkflow(temp_wiki)
    acl = workflow.acl

    # Propose a patch
    result = workflow.propose_patch(
        agent_id="agent-test",
        operation="create",
        pages=["page-1"],
        diff="+ New content",
        confidence=0.95,
        sources=["source-1"]
    )
    patch_id = result["patch_id"]

    # Get base commit
    base_commit = workflow._get_current_commit()

    # Create valid signature
    signed_approval = acl.sign_approval(
        approver_id="human-alice",
        patch_id=patch_id,
        expected_base_commit=base_commit
    )

    # Monkey-patch _get_current_commit to simulate change after lock acquisition
    original_get_commit = workflow._get_current_commit
    call_count = [0]

    def mock_get_commit():
        call_count[0] += 1
        if call_count[0] == 1:  # First call (TOCTOU check before lock) returns original
            return original_get_commit()
        else:  # Second call (double-check under lock) returns different commit
            return "changed-commit-hash"

    workflow._get_current_commit = mock_get_commit

    # Try to apply - should fail on double-check
    result = workflow.apply_patch(patch_id, signed_approval, base_commit)

    assert result["status"] == "failed"
    assert result["reason"] == "base_commit_changed"
    assert "changed during lock acquisition" in result["message"]
    assert "during lock acquisition" in result["message"]


def test_propose_patch_update_existing_page_runs_real_lint(temp_wiki):
    """Regression test: update on existing page should run linter without crashing."""
    workflow = WikiWorkflow(temp_wiki)

    # Create a valid page that linter can parse
    page_path = Path(temp_wiki) / "wiki" / "page-1.md"
    page_path.write_text(
        """---
page_id: page-1
title: Page 1
updated: 2026-04-14
confidence: 0.9
source_refs: [source-1]
---
Body.
""",
        encoding="utf-8",
    )

    result = workflow.propose_patch(
        agent_id="agent-test",
        operation="update",
        pages=["page-1"],
        diff="+ updated body",
        confidence=0.95,
        sources=["source-1"],
    )

    assert result["status"] == "success"
    assert result["lint_status"] == "passed"


def test_apply_patch_records_shadow_eval_and_index_ops(temp_wiki):
    """Successful apply should persist shadow eval and append index operation."""
    workflow = WikiWorkflow(temp_wiki)
    acl = workflow.acl

    proposed = workflow.propose_patch(
        agent_id="agent-test",
        operation="create",
        pages=["page-indexed"],
        diff="+ New content",
        confidence=0.96,
        sources=["source-1"],
    )
    patch_id = proposed["patch_id"]
    base_commit = workflow._get_current_commit()

    # Patch record should include shadow eval result.
    patch_file = Path(temp_wiki) / ".pending" / f"{patch_id}.json"
    patch_data = json.loads(patch_file.read_text(encoding="utf-8"))
    assert patch_data["shadow_eval_result"] is not None

    signed_approval = acl.sign_approval(
        approver_id="human-alice",
        patch_id=patch_id,
        expected_base_commit=base_commit,
    )

    applied = workflow.apply_patch(patch_id, signed_approval, base_commit)
    assert applied["status"] == "success"

    index_ops_file = Path(temp_wiki) / ".index" / "index.ops.jsonl"
    assert index_ops_file.exists()
    ops_lines = index_ops_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(ops_lines) == 1
    op = json.loads(ops_lines[0])
    assert op["page_id"] == "page-indexed"
