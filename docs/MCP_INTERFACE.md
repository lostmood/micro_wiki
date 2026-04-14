# Wiki Engine MCP Interface Specification v1

## Overview

This document defines the MCP tool interface for the Wiki Engine v1.
All interfaces are frozen for v1 - changes require version bump.

## Core Principles

1. **Human approval required**: All write operations require human approval (v1)
2. **Atomic operations**: All state changes are atomic with TOCTOU protection
3. **Audit trail**: All operations are logged with signatures
4. **Anti-replay**: All approvals use nonce + TTL to prevent replay attacks

## Read-Only Tools

### wiki_search

Search wiki pages by query.

**Signature:**
```python
def wiki_search(query: str, scope: str = "all", limit: int = 10) -> List[Page]
```

**Parameters:**
- `query`: Search query string
- `scope`: Search scope ("docs" / "memory" / "threads" / "sessions" / "all")
- `limit`: Maximum number of results

**Returns:**
```python
[
    {
        "page_id": "concept-transformer",
        "title": "Transformer Architecture",
        "summary": "...",
        "relevance_score": 0.95
    }
]
```

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
    "total_pages": 42,
    "total_sources": 15,
    "pending_patches": 3,
    "last_update": "2026-04-14T04:00:00Z",
    "health": "healthy"
}
```

## Write Tools (Two-Phase)

### wiki_ingest

Ingest a new source document into the wiki.

**Signature:**
```python
def wiki_ingest(source_path: str, agent_id: str) -> dict
```

**Parameters:**
- `source_path`: Path to source document
- `agent_id`: ID of the agent performing ingestion

**Returns:**
```python
{
    "status": "success",
    "patch_id": "patch-20260414-035500",
    "affected_pages": ["concept-transformer", "paper-attention"],
    "lint_status": "passed"
}
```

**Error Response:**
```python
{
    "status": "failed",
    "reason": "lint_failed",
    "errors": ["missing_source_refs", "broken_link"]
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
    "confidence": 0.95
    # Note: shadow_eval is NOT included in response (hidden by default per approval_policy.yaml)
    # Only visible in diagnostic mode or post-analysis
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
def wiki_list_conflicts(status: str = "pending") -> List[Conflict]
```

**Parameters:**
- `status`: Conflict status ("pending" / "resolved" / "all")

**Returns:**
```python
[
    {
        "conflict_id": "conflict-abc123",
        "type": "semantic_level",
        "detected_at": 1713067500.123,
        "patches": ["patch-001", "patch-002"],
        "status": "pending"
    }
]
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
def wiki_lint(scope: str = "all") -> LintReport
```

**Parameters:**
- `scope`: Lint scope ("all" / "pending" / "recent")

**Returns:**
```python
{
    "status": "passed",
    "checks": [
        {"name": "frontmatter_validation", "passed": true},
        {"name": "dead_link_check", "passed": true},
        {"name": "orphan_page_check", "passed": true},
        {"name": "reference_existence", "passed": true},
        {"name": "duplicate_topic_check", "passed": true}
    ],
    "errors": [],
    "warnings": []
}
```

### wiki_rollback

Rollback a change (requires approval).

**Signature:**
```python
def wiki_rollback(
    change_id: str,
    approved_by: str,
    reason: str
) -> dict
```

**Parameters:**
- `change_id`: ID of the change to rollback
- `approved_by`: ID of the approver
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

**Error Response:**
```python
{
    "status": "failed",
    "reason": "operation_type_not_rollbackable",
    "operation_type": "schema_change",
    "requires": "manual_intervention"
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
