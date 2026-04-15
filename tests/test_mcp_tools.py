"""
Contract tests for MCP tools.

Tests verify:
1. Functional correctness (success and failure paths)
2. Zero side effects for read-only operations
3. Write operations delegate to workflow correctly
"""

import os
import json
import subprocess
import hashlib
import yaml
from pathlib import Path
import pytest

from wiki_engine.mcp_tools import (
    wiki_read,
    wiki_status,
    wiki_search,
    wiki_propose_patch,
    wiki_apply_patch,
    wiki_graph_neighbors,
    wiki_ingest,
    wiki_list_conflicts,
    wiki_resolve_conflict,
    wiki_lint,
    wiki_rollback,
)
from wiki_engine.acl import ApprovalACL


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


def test_wiki_search_unsupported_scope_returns_warning(temp_wiki):
    """Test wiki_search with unsupported scope returns warning."""
    result = wiki_search(temp_wiki, "test", limit=10, scope="title_only")

    assert result["status"] == "success"
    assert "warnings" in result
    assert len(result["warnings"]) == 1
    assert "unsupported_scope" in result["warnings"][0]
    assert "title_only" in result["warnings"][0]


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


# ============================================================================
# wiki_graph_neighbors tests
# ============================================================================

def test_wiki_graph_neighbors_returns_connected_nodes(temp_wiki):
    """Graph query should return linked neighbors."""
    page_a = """---
page_id: graph-a
title: Graph A
updated: 1234567890.0
confidence: 0.95
source_refs: [source-1]
---
See [[graph-b]].
"""
    page_b = """---
page_id: graph-b
title: Graph B
updated: 1234567890.0
confidence: 0.95
source_refs: [source-1]
---
Backlink to [[graph-a]].
"""
    (Path(temp_wiki) / "wiki" / "concepts" / "graph-a.md").write_text(page_a)
    (Path(temp_wiki) / "wiki" / "concepts" / "graph-b.md").write_text(page_b)

    result = wiki_graph_neighbors(temp_wiki, "graph-a", depth=1)

    assert result["status"] == "success"
    node_ids = {node["page_id"] for node in result["nodes"]}
    assert {"graph-a", "graph-b"} <= node_ids
    assert any(edge["from"] == "graph-a" and edge["to"] == "graph-b" for edge in result["edges"])


def test_wiki_graph_neighbors_missing_page_fails(temp_wiki):
    """Graph query on nonexistent page should fail."""
    result = wiki_graph_neighbors(temp_wiki, "missing-page", depth=1)
    assert result["status"] == "failed"
    assert result["reason"] == "page_not_found"


# ============================================================================
# wiki_ingest tests
# ============================================================================

def test_wiki_ingest_proposes_patch_from_source_file(temp_wiki):
    """Ingest should create a workflow patch from source content."""
    source_file = Path(temp_wiki) / "notes-source.md"
    source_file.write_text("Ingested content body.", encoding="utf-8")

    result = wiki_ingest(temp_wiki, str(source_file), "agent-ingest")

    assert result["status"] == "success"
    assert "patch_id" in result
    assert result["requires_approval"] is True
    assert result["affected_pages"] == ["notes-source"]


def test_wiki_ingest_missing_source_fails(temp_wiki):
    """Ingest on missing file should return source_not_found."""
    result = wiki_ingest(temp_wiki, "missing-source.md", "agent-ingest")
    assert result["status"] == "failed"
    assert result["reason"] == "source_not_found"


# ============================================================================
# wiki_conflict tests
# ============================================================================

def test_wiki_list_conflicts_detects_page_overlap(temp_wiki):
    """Conflict list should detect overlapping pending patches."""
    wiki_propose_patch(
        wiki_root=temp_wiki,
        agent_id="agent-a",
        operation="update",
        pages=["test-page"],
        diff="+ A",
        confidence=0.9,
        sources=["source-1"],
    )
    wiki_propose_patch(
        wiki_root=temp_wiki,
        agent_id="agent-b",
        operation="update",
        pages=["test-page"],
        diff="+ B",
        confidence=0.9,
        sources=["source-2"],
    )

    result = wiki_list_conflicts(temp_wiki, status="pending")

    assert result["status"] == "success"
    assert result["total"] >= 1
    assert all(conflict["status"] == "pending" for conflict in result["conflicts"])


def test_wiki_resolve_conflict_marks_conflict_resolved(temp_wiki):
    """Resolving conflict should persist resolution and change list filter result."""
    wiki_propose_patch(
        wiki_root=temp_wiki,
        agent_id="agent-a",
        operation="update",
        pages=["test-page"],
        diff="+ A",
        confidence=0.9,
        sources=["source-1"],
    )
    wiki_propose_patch(
        wiki_root=temp_wiki,
        agent_id="agent-b",
        operation="update",
        pages=["test-page"],
        diff="+ B",
        confidence=0.9,
        sources=["source-2"],
    )
    pending_conflicts = wiki_list_conflicts(temp_wiki, status="pending")
    conflict_id = pending_conflicts["conflicts"][0]["conflict_id"]

    resolve_result = wiki_resolve_conflict(
        wiki_root=temp_wiki,
        conflict_id=conflict_id,
        action="accept_patch_001",
        resolver="human-alice",
        reason="Patch A has better source quality",
    )

    assert resolve_result["status"] == "success"
    assert resolve_result["conflict_id"] == conflict_id

    resolved_conflicts = wiki_list_conflicts(temp_wiki, status="resolved")
    assert any(conflict["conflict_id"] == conflict_id for conflict in resolved_conflicts["conflicts"])


def test_wiki_resolve_conflict_rejects_empty_resolver(temp_wiki):
    """Resolve conflict should reject empty resolver (minimal defense)."""
    wiki_propose_patch(
        wiki_root=temp_wiki,
        agent_id="agent-a",
        operation="update",
        pages=["test-page"],
        diff="+ A",
        confidence=0.9,
        sources=["source-1"],
    )
    wiki_propose_patch(
        wiki_root=temp_wiki,
        agent_id="agent-b",
        operation="update",
        pages=["test-page"],
        diff="+ B",
        confidence=0.9,
        sources=["source-2"],
    )
    pending_conflicts = wiki_list_conflicts(temp_wiki, status="pending")
    conflict_id = pending_conflicts["conflicts"][0]["conflict_id"]

    result = wiki_resolve_conflict(
        wiki_root=temp_wiki,
        conflict_id=conflict_id,
        action="accept",
        resolver="",  # Empty resolver
        reason="Valid reason",
    )
    assert result["status"] == "failed"
    assert result["reason"] == "invalid_resolver"


def test_wiki_resolve_conflict_rejects_empty_reason(temp_wiki):
    """Resolve conflict should reject empty reason (minimal defense)."""
    wiki_propose_patch(
        wiki_root=temp_wiki,
        agent_id="agent-a",
        operation="update",
        pages=["test-page"],
        diff="+ A",
        confidence=0.9,
        sources=["source-1"],
    )
    wiki_propose_patch(
        wiki_root=temp_wiki,
        agent_id="agent-b",
        operation="update",
        pages=["test-page"],
        diff="+ B",
        confidence=0.9,
        sources=["source-2"],
    )
    pending_conflicts = wiki_list_conflicts(temp_wiki, status="pending")
    conflict_id = pending_conflicts["conflicts"][0]["conflict_id"]

    result = wiki_resolve_conflict(
        wiki_root=temp_wiki,
        conflict_id=conflict_id,
        action="accept",
        resolver="human-alice",
        reason="   ",  # Whitespace-only reason
    )
    assert result["status"] == "failed"
    assert result["reason"] == "invalid_reason"


# ============================================================================
# wiki_lint tests
# ============================================================================

def test_wiki_lint_all_detects_missing_frontmatter(temp_wiki):
    """Standalone lint should report errors for malformed wiki files."""
    bad_page = Path(temp_wiki) / "wiki" / "concepts" / "bad-page.md"
    bad_page.write_text("no frontmatter here", encoding="utf-8")

    result = wiki_lint(temp_wiki, scope="all")

    assert result["status"] == "failed"
    assert result["errors_count"] > 0
    assert any(error["code"] == "missing_frontmatter" for error in result["errors"])


def test_wiki_lint_invalid_scope_fails(temp_wiki):
    """Invalid lint scope should return a typed failure."""
    result = wiki_lint(temp_wiki, scope="invalid")
    assert result["status"] == "failed"
    assert result["reason"] == "invalid_scope"


# ============================================================================
# wiki_rollback tests
# ============================================================================

def test_wiki_rollback_reverts_change_commit(temp_wiki):
    """Rollback should revert a commit identified by Change ID marker."""
    change_id = "ch-test-rollback-001"
    target_file = Path(temp_wiki) / "wiki" / "rollback-page.md"
    target_file.write_text("before rollback\n", encoding="utf-8")
    os.system(f"cd {temp_wiki} && git add wiki/rollback-page.md")
    os.system(f"cd {temp_wiki} && git commit -m 'Apply update\n\nChange ID: {change_id}\n\n[human-alice🐾]'")

    # Get current commit for TOCTOU protection
    expected_base = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=temp_wiki,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    # Generate signed approval
    acl = ApprovalACL(f"{temp_wiki}/.schema/approvers.yaml")
    signed_approval = acl.sign_approval(
        approver_id="human-alice",
        patch_id=change_id,
        expected_base_commit=expected_base,
    )

    result = wiki_rollback(
        wiki_root=temp_wiki,
        change_id=change_id,
        signed_approval=signed_approval,
        expected_base_commit=expected_base,
        reason="Regression detected",
    )

    assert result["status"] == "success"
    assert result["original_change_id"] == change_id
    assert "rollback_change_id" in result


def test_wiki_rollback_missing_change_fails(temp_wiki):
    """Rollback should fail when change_id is not found."""
    expected_base = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=temp_wiki,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    acl = ApprovalACL(f"{temp_wiki}/.schema/approvers.yaml")
    signed_approval = acl.sign_approval(
        approver_id="human-alice",
        patch_id="ch-not-exists",
        expected_base_commit=expected_base,
    )

    result = wiki_rollback(
        wiki_root=temp_wiki,
        change_id="ch-not-exists",
        signed_approval=signed_approval,
        expected_base_commit=expected_base,
        reason="No-op",
    )
    assert result["status"] == "failed"
    assert result["reason"] == "change_not_found"


def test_wiki_rollback_rejects_patch_id_mismatch(temp_wiki):
    """Rollback should reject when signed_approval.patch_id != change_id."""
    change_id = "ch-rollback-002"
    target_file = Path(temp_wiki) / "wiki" / "rollback-page2.md"
    target_file.write_text("content\n", encoding="utf-8")
    os.system(f"cd {temp_wiki} && git add wiki/rollback-page2.md")
    os.system(f"cd {temp_wiki} && git commit -m 'Apply\n\nChange ID: {change_id}\n\n[human-alice🐾]'")

    expected_base = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=temp_wiki,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    acl = ApprovalACL(f"{temp_wiki}/.schema/approvers.yaml")
    signed_approval = acl.sign_approval(
        approver_id="human-alice",
        patch_id="ch-different-id",  # Mismatch
        expected_base_commit=expected_base,
    )

    result = wiki_rollback(
        wiki_root=temp_wiki,
        change_id=change_id,
        signed_approval=signed_approval,
        expected_base_commit=expected_base,
        reason="Test",
    )
    assert result["status"] == "failed"
    assert result["reason"] == "patch_id_mismatch"


def test_wiki_rollback_rejects_signature_replay(temp_wiki):
    """Rollback should reject replayed signature (nonce reuse)."""
    change_id = "ch-rollback-003"
    target_file = Path(temp_wiki) / "wiki" / "rollback-page3.md"
    target_file.write_text("content\n", encoding="utf-8")
    os.system(f"cd {temp_wiki} && git add wiki/rollback-page3.md")
    os.system(f"cd {temp_wiki} && git commit -m 'Apply\n\nChange ID: {change_id}\n\n[human-alice🐾]'")

    expected_base = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=temp_wiki,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    acl = ApprovalACL(f"{temp_wiki}/.schema/approvers.yaml")
    signed_approval = acl.sign_approval(
        approver_id="human-alice",
        patch_id=change_id,
        expected_base_commit=expected_base,
    )

    # First rollback succeeds
    result1 = wiki_rollback(
        wiki_root=temp_wiki,
        change_id=change_id,
        signed_approval=signed_approval,
        expected_base_commit=expected_base,
        reason="First rollback",
    )
    assert result1["status"] == "success"

    # Replay same signature should fail (nonce already used)
    new_base = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=temp_wiki,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    result2 = wiki_rollback(
        wiki_root=temp_wiki,
        change_id=change_id,
        signed_approval=signed_approval,  # Reused signature
        expected_base_commit=new_base,
        reason="Replay attempt",
    )
    assert result2["status"] == "failed"
    assert "signature_verification_failed" in result2["reason"]


def test_wiki_rollback_detects_base_commit_change(temp_wiki):
    """Rollback should detect TOCTOU when base commit changes."""
    change_id = "ch-rollback-004"
    target_file = Path(temp_wiki) / "wiki" / "rollback-page4.md"
    target_file.write_text("content\n", encoding="utf-8")
    os.system(f"cd {temp_wiki} && git add wiki/rollback-page4.md")
    os.system(f"cd {temp_wiki} && git commit -m 'Apply\n\nChange ID: {change_id}\n\n[human-alice🐾]'")

    old_base = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=temp_wiki,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    # Simulate concurrent change
    dummy_file = Path(temp_wiki) / "wiki" / "concurrent-change.md"
    dummy_file.write_text("concurrent\n", encoding="utf-8")
    os.system(f"cd {temp_wiki} && git add wiki/concurrent-change.md")
    os.system(f"cd {temp_wiki} && git commit -m 'Concurrent change'")

    acl = ApprovalACL(f"{temp_wiki}/.schema/approvers.yaml")
    signed_approval = acl.sign_approval(
        approver_id="human-alice",
        patch_id=change_id,
        expected_base_commit=old_base,
    )

    result = wiki_rollback(
        wiki_root=temp_wiki,
        change_id=change_id,
        signed_approval=signed_approval,
        expected_base_commit=old_base,  # Stale base
        reason="TOCTOU test",
    )
    assert result["status"] == "failed"
    assert result["reason"] == "base_commit_changed"


def test_wiki_rollback_rejects_unauthorized_approver(temp_wiki):
    """Rollback should reject unauthorized approver."""
    change_id = "ch-rollback-005"
    target_file = Path(temp_wiki) / "wiki" / "rollback-page5.md"
    target_file.write_text("content\n", encoding="utf-8")
    os.system(f"cd {temp_wiki} && git add wiki/rollback-page5.md")
    os.system(f"cd {temp_wiki} && git commit -m 'Apply\n\nChange ID: {change_id}\n\n[human-alice🐾]'")

    expected_base = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=temp_wiki,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    # Add unauthorized approver to approvers.yaml temporarily
    approvers_file = Path(temp_wiki) / ".schema" / "approvers.yaml"
    approvers_config = yaml.safe_load(approvers_file.read_text())
    approvers_config["authorized_approvers"].append({
        "id": "human-unauthorized",
        "name": "Unauthorized User",
        "role": "guest",
        "auth_method": "session_identity",
        "permissions": []  # No permissions
    })
    approvers_file.write_text(yaml.dump(approvers_config))

    # Create valid signature with unauthorized approver
    acl = ApprovalACL(f"{temp_wiki}/.schema/approvers.yaml")
    signed_approval = acl.sign_approval(
        approver_id="human-unauthorized",
        patch_id=change_id,
        expected_base_commit=expected_base,
    )

    result = wiki_rollback(
        wiki_root=temp_wiki,
        change_id=change_id,
        signed_approval=signed_approval,
        expected_base_commit=expected_base,
        reason="Test unauthorized",
    )
    assert result["status"] == "failed"
    assert result["reason"] == "insufficient_permission"


def test_wiki_rollback_rejects_signature_base_commit_mismatch(temp_wiki):
    """Rollback should reject when signed_approval.expected_base_commit != parameter."""
    change_id = "ch-rollback-006"
    target_file = Path(temp_wiki) / "wiki" / "rollback-page6.md"
    target_file.write_text("content\n", encoding="utf-8")
    os.system(f"cd {temp_wiki} && git add wiki/rollback-page6.md")
    os.system(f"cd {temp_wiki} && git commit -m 'Apply\n\nChange ID: {change_id}\n\n[human-alice🐾]'")

    expected_base = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=temp_wiki,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    acl = ApprovalACL(f"{temp_wiki}/.schema/approvers.yaml")
    signed_approval = acl.sign_approval(
        approver_id="human-alice",
        patch_id=change_id,
        expected_base_commit=expected_base,
    )

    # Pass different expected_base_commit parameter (mismatch with signature)
    fake_base = "0" * 40

    result = wiki_rollback(
        wiki_root=temp_wiki,
        change_id=change_id,
        signed_approval=signed_approval,
        expected_base_commit=fake_base,  # Mismatch
        reason="Test mismatch",
    )
    assert result["status"] == "failed"
    assert result["reason"] == "signature_base_commit_mismatch"
