"""
Contract tests for MCP tools.

Tests verify:
1. Functional correctness (success and failure paths)
2. Zero side effects for read-only operations
3. Write operations delegate to workflow correctly
"""

import os
import json
import hashlib
from pathlib import Path
import pytest

from wiki_engine.mcp_tools import (
    wiki_read,
    wiki_status,
    wiki_search,
    wiki_propose_patch,
    wiki_apply_patch
)


@pytest.fixture
def temp_wiki(tmp_path):
    """Create a temporary wiki structure for testing."""
    wiki_root = tmp_path / "test_wiki"
    wiki_root.mkdir()

    # Initialize git repo
    os.system(f"cd {wiki_root} && git init && git config user.email 'test@test.com' && git config user.name 'Test'")

    # Create directory structure
    (wiki_root / "wiki").mkdir()
    (wiki_root / "wiki" / "concepts").mkdir()
    (wiki_root / "wiki" / "entities").mkdir()
    (wiki_root / "wiki" / "explorations").mkdir()
    (wiki_root / ".pending").mkdir()
    (wiki_root / ".audit").mkdir()
    (wiki_root / ".schema").mkdir()

    # Create schema files
    (wiki_root / ".schema" / "approval_policy.yaml").write_text("""
mode: manual
auto_apply_enabled: false
shadow_eval_enabled: true
confidence_usage: advisory
""")

    (wiki_root / ".schema" / "approvers.yaml").write_text("""
version: "v1"

signature:
  ttl_seconds: 300
  nonce_bits: 128
  algorithm: "hmac_sha256"
  cleanup_interval_hours: 1

authorized_approvers:
  - id: "human-alice"
    name: "Alice"
    role: "reviewer"
    auth_method: "session_identity"
    permissions: ["approve_all"]
  - id: "human-bob"
    name: "Bob"
    role: "reviewer"
    auth_method: "session_identity"
    permissions: ["approve_all"]

operation_permissions:
  approve_all:
    - "*"

audit:
  require_signature: true
  signature_method: "hmac_sha256"
  log_all_attempts: true
  audit_dir: ".audit"
""")

    # Create a sample page
    page_content = """---
page_id: test-page
title: Test Page
updated: 1234567890.0
confidence: 0.95
source_refs: [source-1]
category: concepts
---

This is a test page content.
"""
    (wiki_root / "wiki" / "concepts" / "test-page.md").write_text(page_content)

    # Initial commit
    os.system(f"cd {wiki_root} && git add -A && git commit -m 'Initial commit'")

    return str(wiki_root)


def compute_dir_hash(directory: Path) -> str:
    """Compute hash of all files in directory for side-effect detection."""
    hasher = hashlib.sha256()

    if not directory.exists():
        return hasher.hexdigest()

    for file_path in sorted(directory.rglob("*")):
        if file_path.is_file() and not file_path.name.endswith(".lock"):
            hasher.update(file_path.read_bytes())

    return hasher.hexdigest()


# ============================================================================
# wiki_read tests
# ============================================================================

def test_wiki_read_existing_page_success(temp_wiki):
    """Test reading an existing page returns correct content."""
    result = wiki_read(temp_wiki, "test-page")

    assert result["status"] == "success"
    assert result["page_id"] == "test-page"
    assert result["title"] == "Test Page"
    assert "This is a test page content" in result["content"]
    assert result["metadata"]["confidence"] == 0.95
    assert result["metadata"]["source_refs"] == ["source-1"]


def test_wiki_read_nonexistent_page_fails(temp_wiki):
    """Test reading a nonexistent page returns failure."""
    result = wiki_read(temp_wiki, "nonexistent-page")

    assert result["status"] == "failed"
    assert result["reason"] == "page_not_found"
    assert "nonexistent-page" in result["message"]


def test_wiki_read_subdir_page_success(temp_wiki):
    """Test reading a page in subdirectory works."""
    # Create a page in entities subdirectory
    page_content = """---
page_id: entity-1
title: Entity 1
updated: 1234567890.0
confidence: 0.9
source_refs: [source-2]
---

Entity content.
"""
    (Path(temp_wiki) / "wiki" / "entities" / "entity-1.md").write_text(page_content)

    result = wiki_read(temp_wiki, "entity-1")

    assert result["status"] == "success"
    assert result["page_id"] == "entity-1"
    assert result["title"] == "Entity 1"


def test_wiki_read_no_side_effects(temp_wiki):
    """Test wiki_read does not modify any files."""
    wiki_dir = Path(temp_wiki) / "wiki"
    pending_dir = Path(temp_wiki) / ".pending"

    hash_before_wiki = compute_dir_hash(wiki_dir)
    hash_before_pending = compute_dir_hash(pending_dir)

    # Perform read operation
    wiki_read(temp_wiki, "test-page")

    hash_after_wiki = compute_dir_hash(wiki_dir)
    hash_after_pending = compute_dir_hash(pending_dir)

    assert hash_before_wiki == hash_after_wiki
    assert hash_before_pending == hash_after_pending


# ============================================================================
# wiki_status tests
# ============================================================================

def test_wiki_status_returns_correct_stats(temp_wiki):
    """Test wiki_status returns correct statistics."""
    result = wiki_status(temp_wiki)

    assert result["status"] == "success"
    assert result["total_pages"] == 1  # Only test-page
    assert result["pending_patches"] == 0
    assert result["health"] == "healthy"
    assert result["last_update"] is not None  # Has git commit


def test_wiki_status_empty_wiki_returns_zero(temp_wiki):
    """Test wiki_status on empty wiki returns zero counts."""
    # Remove the test page
    (Path(temp_wiki) / "wiki" / "concepts" / "test-page.md").unlink()

    result = wiki_status(temp_wiki)

    assert result["status"] == "success"
    assert result["total_pages"] == 0
    assert result["pending_patches"] == 0


def test_wiki_status_no_side_effects(temp_wiki):
    """Test wiki_status does not modify any files."""
    wiki_dir = Path(temp_wiki) / "wiki"
    pending_dir = Path(temp_wiki) / ".pending"

    hash_before_wiki = compute_dir_hash(wiki_dir)
    hash_before_pending = compute_dir_hash(pending_dir)

    # Perform status operation
    wiki_status(temp_wiki)

    hash_after_wiki = compute_dir_hash(wiki_dir)
    hash_after_pending = compute_dir_hash(pending_dir)

    assert hash_before_wiki == hash_after_wiki
    assert hash_before_pending == hash_after_pending


# ============================================================================
# wiki_search tests
# ============================================================================

def test_wiki_search_finds_matching_pages(temp_wiki):
    """Test wiki_search finds pages matching query."""
    result = wiki_search(temp_wiki, "test", limit=10)

    assert result["status"] == "success"
    assert result["total"] == 1
    assert len(result["results"]) == 1
    assert result["results"][0]["page_id"] == "concepts-test-page"
    assert result["results"][0]["title"] == "Test Page"
    assert result["results"][0]["relevance_score"] > 0


def test_wiki_search_no_match_returns_empty(temp_wiki):
    """Test wiki_search with no matches returns empty list."""
    result = wiki_search(temp_wiki, "nonexistent-query", limit=10)

    assert result["status"] == "success"
    assert result["total"] == 0
    assert result["results"] == []


def test_wiki_search_respects_limit(temp_wiki):
    """Test wiki_search respects the limit parameter."""
    # Create multiple pages
    for i in range(5):
        page_content = f"""---
page_id: page-{i}
title: Test Page {i}
updated: 1234567890.0
confidence: 0.9
source_refs: [source-1]
---

Test content {i}.
"""
        (Path(temp_wiki) / "wiki" / f"page-{i}.md").write_text(page_content)

    result = wiki_search(temp_wiki, "test", limit=3)

    assert result["status"] == "success"
    assert len(result["results"]) <= 3


def test_wiki_search_no_side_effects(temp_wiki):
    """Test wiki_search does not modify any files."""
    wiki_dir = Path(temp_wiki) / "wiki"
    pending_dir = Path(temp_wiki) / ".pending"

    hash_before_wiki = compute_dir_hash(wiki_dir)
    hash_before_pending = compute_dir_hash(pending_dir)

    # Perform search operation
    wiki_search(temp_wiki, "test", limit=10)

    hash_after_wiki = compute_dir_hash(wiki_dir)
    hash_after_pending = compute_dir_hash(pending_dir)

    assert hash_before_wiki == hash_after_wiki
    assert hash_before_pending == hash_after_pending


# ============================================================================
# wiki_propose_patch tests
# ============================================================================

def test_wiki_propose_patch_create_success_lint_passed(temp_wiki):
    """Test proposing a valid patch returns success with lint passed."""
    result = wiki_propose_patch(
        wiki_root=temp_wiki,
        agent_id="agent-test",
        operation="create",
        pages=["new-page"],
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
    assert result["lint_errors"] is None


def test_wiki_propose_patch_create_lint_failed_still_success(temp_wiki):
    """Test proposing a patch with lint failure still returns success status."""
    result = wiki_propose_patch(
        wiki_root=temp_wiki,
        agent_id="agent-test",
        operation="create",
        pages=["bad-page"],
        diff="+ Bad content",
        confidence=0.5,  # Below threshold
        sources=[]  # Missing sources
    )

    assert result["status"] == "success"  # Still success!
    assert "patch_id" in result
    assert result["lint_status"] == "failed"
    assert result["lint_errors"] is not None
    assert len(result["lint_errors"]) > 0


# ============================================================================
# wiki_apply_patch tests
# ============================================================================

def test_wiki_apply_patch_success(temp_wiki):
    """Test applying a valid patch succeeds."""
    from wiki_engine.workflow import WikiWorkflow

    workflow = WikiWorkflow(temp_wiki)

    # Propose a patch
    propose_result = wiki_propose_patch(
        wiki_root=temp_wiki,
        agent_id="agent-test",
        operation="create",
        pages=["apply-test"],
        diff="+ Content",
        confidence=0.95,
        sources=["source-1"]
    )
    patch_id = propose_result["patch_id"]

    # Get base commit
    base_commit = workflow._get_current_commit()

    # Sign approval
    signed_approval = workflow.acl.sign_approval(
        approver_id="human-alice",
        patch_id=patch_id,
        expected_base_commit=base_commit
    )

    # Apply patch
    result = wiki_apply_patch(
        wiki_root=temp_wiki,
        patch_id=patch_id,
        signed_approval=signed_approval,
        expected_base_commit=base_commit
    )

    assert result["status"] == "success"
    assert "change_id" in result
    assert result["change_id"].startswith("ch-")
    assert "commit_hash" in result
    assert "applied_at" in result


def test_wiki_apply_patch_invalid_signature(temp_wiki):
    """Test applying patch with invalid signature fails."""
    # Propose a patch
    propose_result = wiki_propose_patch(
        wiki_root=temp_wiki,
        agent_id="agent-test",
        operation="create",
        pages=["sig-test"],
        diff="+ Content",
        confidence=0.95,
        sources=["source-1"]
    )
    patch_id = propose_result["patch_id"]

    # Create invalid signature
    invalid_approval = {
        "approver_id": "human-alice",
        "patch_id": patch_id,
        "timestamp": 1234567890.0,
        "nonce": "fake-nonce",
        "expires_at": 9999999999.0,
        "expected_base_commit": "fake-commit",
        "signature": "invalid-signature"
    }

    # Apply patch
    result = wiki_apply_patch(
        wiki_root=temp_wiki,
        patch_id=patch_id,
        signed_approval=invalid_approval,
        expected_base_commit="fake-commit"
    )

    assert result["status"] == "failed"
    assert "signature_verification_failed" in result["reason"]


def test_wiki_apply_patch_base_commit_mismatch(temp_wiki):
    """Test applying patch with mismatched base commit fails."""
    from wiki_engine.workflow import WikiWorkflow

    workflow = WikiWorkflow(temp_wiki)

    # Propose a patch
    propose_result = wiki_propose_patch(
        wiki_root=temp_wiki,
        agent_id="agent-test",
        operation="create",
        pages=["commit-test"],
        diff="+ Content",
        confidence=0.95,
        sources=["source-1"]
    )
    patch_id = propose_result["patch_id"]

    # Get base commit
    base_commit = workflow._get_current_commit()

    # Sign approval
    signed_approval = workflow.acl.sign_approval(
        approver_id="human-alice",
        patch_id=patch_id,
        expected_base_commit=base_commit
    )

    # Apply patch with wrong base commit
    result = wiki_apply_patch(
        wiki_root=temp_wiki,
        patch_id=patch_id,
        signed_approval=signed_approval,
        expected_base_commit="wrong-commit-hash"
    )

    assert result["status"] == "failed"
    assert result["reason"] == "base_commit_changed"


def test_wiki_apply_patch_nonexistent_patch(temp_wiki):
    """Test applying nonexistent patch fails."""
    from wiki_engine.workflow import WikiWorkflow

    workflow = WikiWorkflow(temp_wiki)
    base_commit = workflow._get_current_commit()

    # Create signature for nonexistent patch
    signed_approval = workflow.acl.sign_approval(
        approver_id="human-alice",
        patch_id="patch-nonexistent",
        expected_base_commit=base_commit
    )

    # Apply nonexistent patch
    result = wiki_apply_patch(
        wiki_root=temp_wiki,
        patch_id="patch-nonexistent",
        signed_approval=signed_approval,
        expected_base_commit=base_commit
    )

    assert result["status"] == "failed"
    assert result["reason"] == "patch_not_found"
