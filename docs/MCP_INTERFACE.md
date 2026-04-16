# Wiki Engine MCP Interface Specification v1

## Overview

This document defines the MCP tool interface for the Wiki Engine v1.
All interfaces are frozen for v1 - changes require version bump.

## Core Principles

1. **Human approval required**: All write operations require human approval (v1)
   - **Exception**: `wiki_resolve_conflict` is classified as NON-CRITICAL METADATA WRITE and does NOT require signed approval (only writes audit log, does not modify wiki content)
2. **Atomic operations**: All state changes are atomic with TOCTOU protection
3. **Audit trail**: All operations are logged with signatures
4. **Anti-replay**: All approvals use nonce + TTL to prevent replay attacks

## Read-Only Tools

### wiki_search

Search wiki pages by query.

**Signature:**
```python
def wiki_search(query: str, scope: str = None, limit: int = 10) -> Dict[str, Any]
```

**Parameters:**
- `query`: Search query string
- `scope`: **RESERVED for v2** - Currently unsupported. If provided, will return a warning and be ignored. Planned values: `"docs"` / `"memory"` / `"threads"` / `"sessions"` / `"all"`
- `limit`: Maximum number of results

**Returns:**
```python
{
    "status": "success",
    "results": [
        {
            "page_id": "concept-transformer",
            "title": "Transformer Architecture",
            "summary": "...",
            "relevance_score": 0.95
        }
    ],
    "total": 3,
    "warnings": ["unsupported_scope: scope parameter 'docs' is reserved for v2 and currently ignored"]  # Optional, only if scope provided
}
```

**v1 Behavior:**
- `scope` parameter is accepted but ignored
- If `scope` is provided, a warning is added to the response
- All searches operate on the entire wiki (equivalent to future `scope="all"`)

### wiki_read

Read a specific wiki page.

**Signature:**
```python
def wiki_read(page_id: str) -> Page
```

**Parameters:**
- `page_id`: Unique page identifier

**Returns:**
```python
{
    "status": "success",
    "page_id": "concept-transformer",
    "title": "Transformer Architecture",
    "content": "...",
    "metadata": {
        "created": "2026-04-14T03:55:00Z",
        "updated": "2026-04-14T04:00:00Z",
        "confidence": 0.95,
        "source_refs": ["paper-attention-is-all-you-need"]
    }
}
```

### wiki_graph_neighbors

Get neighboring pages in the knowledge graph.

**Signature:**
```python
def wiki_graph_neighbors(page_id: str, depth: int = 1) -> Graph
```

**Parameters:**
- `page_id`: Starting page ID
- `depth`: Traversal depth (1-3)

**Returns:**
```python
{
    "status": "success",
    "page_id": "concept-transformer",
    "depth": 1,
    "nodes": [
        {"page_id": "concept-transformer", "title": "..."},
        {"page_id": "concept-attention", "title": "..."}
    ],
    "edges": [
        {"from": "concept-transformer", "to": "concept-attention", "type": "references"}
    ]
}
```

### wiki_status

Get wiki status and statistics.

**Signature:**
```python
def wiki_status() -> Status
```

**Returns:**
```python
{
    "status": "success",
    "total_pages": 42,
    "pending_patches": 3,
    "last_update": "2026-04-14T04:00:00Z",
    "health": "healthy"
}
```

## Write Tools (Two-Phase)

### wiki_ingest

Ingest a local text file into the wiki by proposing a patch.

**Description:**
Reads a text file from `source_path`, creates or updates a wiki page based on the filename, and proposes a patch for human review. The page ID is derived from the file stem (e.g., `document.txt` → `document`).

**Signature:**
```python
def wiki_ingest(source_path: str, agent_id: str) -> dict
```

**Parameters:**
- `source_path`: Path to local text file (absolute or relative to wiki root)
- `agent_id`: ID of the agent performing ingestion

**Returns:**
```python
{
    "status": "success",
    "patch_id": "patch-20260414-035500",
    "affected_pages": ["document"],
    "source_path": "/path/to/document.txt",
    "requires_approval": true,
    "confidence": 0.9,
    "lint_status": "passed"  # or "failed" if lint errors detected
    # If lint_status is "failed", lint_errors will be present
}
```

**Error Responses:**
```python
# Source file not found
{
    "status": "failed",
    "reason": "source_not_found",
    "message": "Source file '/path/to/document.txt' does not exist"
}

# Empty source file
{
    "status": "failed",
    "reason": "empty_source",
    "message": "Source file '/path/to/document.txt' is empty"
}
```

### wiki_propose_patch

Propose a patch for review.

**Signature:**
```python
def wiki_propose_patch(
    agent_id: str,
    operation: str,
    pages: List[str],
    diff: str,
    confidence: float,
    sources: List[str]
) -> dict
```

**Parameters:**
- `agent_id`: ID of the agent proposing the patch
- `operation`: Operation type ("create" / "update" / "delete")
- `pages`: List of affected page IDs
- `diff`: Unified diff of changes
- `confidence`: Agent's confidence score (0.0-1.0)
- `sources`: List of source references

**Returns:**
```python
{
    "status": "success",
    "patch_id": "patch-20260414-035500",
    "requires_approval": true,
    "confidence": 0.95,
    "lint_status": "passed"  # or "failed" if lint errors detected
    # Note: Even if lint_status is "failed", status is still "success" (patch is saved to .pending/)
    # lint_errors will be present if lint_status is "failed"
    # shadow_eval is NOT included in response (hidden by default per approval_policy.yaml)
}
```

**Example with lint errors:**
```python
{
    "status": "success",
    "patch_id": "patch-20260414-035500",
    "requires_approval": true,
    "confidence": 0.95,
    "lint_status": "failed",
    "lint_errors": [
        {
            "code": "missing_source_refs",
            "file": "wiki/concepts/transformer.md",
            "message": "Field 'source_refs' must be a non-empty list."
        }
    ]
}
```

### wiki_apply_patch

Apply an approved patch (requires signed approval).

**Signature:**
```python
def wiki_apply_patch(
    patch_id: str,
    signed_approval: dict,
    expected_base_commit: str
) -> dict
```

**Parameters:**
- `patch_id`: ID of the patch to apply
- `signed_approval`: Signed approval from authorized approver
  ```python
  {
      "approver_id": "co-creator",
      "patch_id": "patch-20260414-035500",
      "timestamp": 1713067500.123,
      "nonce": "abc123...",
      "expires_at": 1713067800.123,
      "expected_base_commit": "def456...",
      "signature": "hmac_sha256..."
  }
  ```
- `expected_base_commit`: Expected base commit hash (TOCTOU protection)

**Returns:**
```python
{
    "status": "success",
    "change_id": "ch-20260414-035500",
    "commit_hash": "abc123...",
    "applied_at": 1713067500.123
}
```

**Error Responses:**
```python
# Signature verification failed
{
    "status": "failed",
    "reason": "signature_verification_failed: nonce_already_used",
    "message": "Invalid or expired approval signature"
}

# Base commit changed (TOCTOU)
{
    "status": "failed",
    "reason": "base_commit_changed",
    "expected": "abc123...",
    "actual": "def456..."
}

# Unauthorized approver
{
    "status": "failed",
    "reason": "unauthorized_approver",
    "message": "Approver 'user-x' is not authorized"
}

# Insufficient permission
{
    "status": "failed",
    "reason": "insufficient_permission",
    "message": "Approver 'user-x' cannot approve 'delete_page'"
}
```

## Conflict Management Tools

### wiki_list_conflicts

List pending conflicts.

**Signature:**
```python
def wiki_list_conflicts(status: str = "pending") -> Dict[str, Any]
```

**Parameters:**
- `status`: Conflict status ("pending" / "resolved" / "all")

**Returns:**
```python
{
    "status": "success",
    "conflicts": [
        {
            "conflict_id": "conflict-abc123",
            "type": "page_overlap",
            "detected_at": 1713067500.123,
            "patches": ["patch-001", "patch-002"],
            "pages": ["concept-transformer"],
            "status": "pending"
        }
    ],
    "total": 1
}
```

### wiki_resolve_conflict

Resolve a conflict.

**Signature:**
```python
def wiki_resolve_conflict(
    conflict_id: str,
    action: str,
    resolver: str,
    reason: str
) -> dict
```

**Parameters:**
- `conflict_id`: ID of the conflict
- `action`: Resolution action ("accept_patch_001" / "create_comparison" / "reject_both")
- `resolver`: ID of the resolver
- `reason`: Reason for resolution

**Returns:**
```python
{
    "status": "success",
    "change_id": "ch-20260414-035600",
    "resolution": "accepted_patch_001"
}
```

## Maintenance Tools

### wiki_lint

Run lint checks on wiki content.

**Signature:**
```python
def wiki_lint(scope: str = "all") -> Dict[str, Any]
```

**Parameters:**
- `scope`: Lint scope - `"all"` (all pages) / `"pending"` (pages affected by pending patches) / `"recent"` (pages changed in last commit)

**Returns:**
```python
{
    "status": "passed",
    "scope": "all",
    "checked_files": ["wiki/concepts/transformer.md", "wiki/papers/attention.md"],
    "checks": [
        {"name": "frontmatter_validation", "passed": true},
        {"name": "required_fields", "passed": true},
        {"name": "confidence_range", "passed": true},
        {"name": "source_refs", "passed": true},
        {"name": "duplicate_page_id", "passed": true},
        {"name": "dead_link_check", "passed": true}
    ],
    "errors": [],
    "warnings": [],
    "errors_count": 0,
    "warnings_count": 0
}
```

**Error Response (invalid scope):**
```python
{
    "status": "failed",
    "reason": "invalid_scope",
    "message": "scope must be one of: all, pending, recent"
}
```

**v1 Behavior:**
- `scope="all"`: Lint all `.md` files in `wiki/` directory
- `scope="pending"`: Lint only pages affected by patches in `.pending/`
- `scope="recent"`: Lint only pages changed in `HEAD~1..HEAD` (requires git)

### wiki_rollback

Rollback a change (requires approval).

**Signature:**
```python
def wiki_rollback(
    change_id: str,
    signed_approval: Dict[str, Any],
    expected_base_commit: str,
    reason: str
) -> dict
```

**Parameters:**
- `change_id`: ID of the change to rollback
- `signed_approval`: Signed approval object (from ACL, same structure as wiki_apply_patch)
- `expected_base_commit`: Expected git commit hash (TOCTOU protection)
- `reason`: Reason for rollback

**Returns:**
```python
{
    "status": "success",
    "rollback_change_id": "ch-20260414-035700",
    "original_change_id": "ch-20260414-035500",
    "rolled_back_at": 1713067700.123
}
```

**Error Responses:**
```python
# Patch ID mismatch
{
    "status": "failed",
    "reason": "patch_id_mismatch",
    "message": "signed_approval.patch_id 'patch-002' does not match change_id 'patch-001'"
}

# Signature base commit mismatch
{
    "status": "failed",
    "reason": "signature_base_commit_mismatch",
    "message": "Signature's expected_base_commit does not match provided value"
}

# Base commit changed (TOCTOU)
{
    "status": "failed",
    "reason": "base_commit_changed",
    "message": "Base commit changed: expected abc123..., got def456..."
}

# Insufficient permission
{
    "status": "failed",
    "reason": "insufficient_permission",
    "message": "Approver 'user-x' cannot approve rollback operations"
}
```

## Approval Workflow

### Step 1: Generate Approval Signature

Use ACL to generate a signed approval:

```python
from wiki_engine.acl import ApprovalACL

acl = ApprovalACL(".schema/approvers.yaml")

signed_approval = acl.sign_approval(
    approver_id="co-creator",
    patch_id="patch-20260414-035500",
    expected_base_commit="abc123..."
)
```

### Step 2: Apply Patch with Signature

```python
result = wiki_apply_patch(
    patch_id="patch-20260414-035500",
    signed_approval=signed_approval,
    expected_base_commit="abc123..."
)
```

### Security Guarantees

1. **Anti-replay**: Each signature can only be used once (nonce tracking)
2. **Time-bound**: Signatures expire after TTL (default 5 minutes)
3. **TOCTOU protection**: Base commit must match expected value
4. **Atomic nonce check**: Nonce check and consumption are atomic (flock protected)
5. **Audit trail**: All approvals are logged with full signature

## Version History

- **v1.0** (2026-04-14): Initial release
  - All write operations require human approval
  - Anti-replay signatures with nonce + TTL
  - TOCTOU protection with expected_base_commit
  - Atomic nonce check+consume
