# Micro Wiki MCP - Quick Start Guide

## What is Micro Wiki?

Micro Wiki is an MCP server that provides a human-in-the-loop knowledge management system. It allows AI agents to propose changes to a structured wiki, with all write operations requiring human approval.

## Key Features

- **11 MCP Tools**: Search, read, propose, apply, rollback, conflict resolution, and more
- **Human-in-the-Loop**: All write operations require cryptographically signed approval
- **Anti-Replay Protection**: Signatures are single-use with TTL expiration
- **TOCTOU Protection**: Base commit verification prevents race conditions
- **Full Audit Trail**: All operations logged with signatures

## Installation

See [DEPLOYMENT.md](DEPLOYMENT.md) for detailed installation instructions.

Quick setup:
```bash
git clone <repository-url>
cd micro_wiki

# Add to PYTHONPATH for development
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
```

## Basic Workflow

### 1. Read-Only Operations (No Approval Required)

#### Search for Pages

```
Use wiki_search with query "transformer" to find relevant pages
```

Response:
```json
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
  "total": 1
}
```

#### Read a Page

```
Use wiki_read with page_id "concept-transformer"
```

Response:
```json
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

#### Check Wiki Status

```
Use wiki_status to get wiki statistics
```

Response:
```json
{
  "status": "success",
  "total_pages": 42,
  "pending_patches": 3,
  "last_update": "2026-04-14T04:00:00Z",
  "health": "healthy"
}
```

#### Explore Knowledge Graph

```
Use wiki_graph_neighbors with page_id "concept-transformer" and depth 1
```

Response:
```json
{
  "nodes": [
    {"page_id": "concept-transformer", "title": "Transformer Architecture"},
    {"page_id": "concept-attention", "title": "Attention Mechanism"}
  ],
  "edges": [
    {"from": "concept-transformer", "to": "concept-attention", "type": "references"}
  ]
}
```

### 2. Write Operations (Require Approval)

#### Step 1: Propose a Patch

```
Use wiki_propose_patch with:
- agent_id: "claude-assistant"
- operation: "create"
- pages: ["concept-gpt"]
- diff: "# GPT Architecture\n\nGPT is a decoder-only transformer..."
- confidence: 0.95
- sources: ["paper-gpt-3"]
```

Response:
```json
{
  "status": "success",
  "patch_id": "patch-20260415-083000",
  "requires_approval": true,
  "confidence": 0.95
}
```

#### Step 2: Human Reviews and Approves

The human reviewer:
1. Reviews the proposed changes in `.pending/patch-20260415-083000.json`
2. Checks the diff and metadata
3. Generates a signed approval (done by the MCP client or approval tool)

#### Step 3: Apply the Patch

```
Use wiki_apply_patch with:
- patch_id: "patch-20260415-083000"
- signed_approval: {
    "approver_id": "co-creator",
    "patch_id": "patch-20260415-083000",
    "timestamp": 1713163800.123,
    "nonce": "abc123...",
    "expected_base_commit": "def456...",
    "signature": "hmac_sha256..."
  }
- expected_base_commit: "def456..."
```

Response:
```json
{
  "status": "success",
  "change_id": "ch-20260415-083000",
  "commit_hash": "abc789...",
  "applied_at": 1713163800.123
}
```

### 3. Conflict Resolution

#### List Conflicts

```
Use wiki_list_conflicts with status "pending"
```

Response:
```json
{
  "status": "success",
  "conflicts": [
    {
      "conflict_id": "conflict-abc123",
      "type": "page_overlap",
      "detected_at": 1713163800.123,
      "patches": ["patch-001", "patch-002"],
      "status": "pending"
    }
  ],
  "total": 1
}
```

#### Resolve a Conflict

```
Use wiki_resolve_conflict with:
- conflict_id: "conflict-abc123"
- action: "accept_patch_001"
- resolver: "co-creator"
- reason: "Patch 001 has higher confidence and better sources"
```

Response:
```json
{
  "status": "success",
  "change_id": "ch-20260415-083100",
  "resolution": "accepted_patch_001"
}
```

### 4. Maintenance Operations

#### Run Lint Checks

```
Use wiki_lint with scope "all"
```

Response:
```json
{
  "status": "passed",
  "checks": [
    {"name": "frontmatter_validation", "passed": true},
    {"name": "required_fields", "passed": true},
    {"name": "confidence_range", "passed": true},
    {"name": "source_refs", "passed": true},
    {"name": "duplicate_page_id", "passed": true},
    {"name": "dead_link_check", "passed": true}
  ],
  "errors": [],
  "warnings": []
}
```

#### Rollback a Change

```
Use wiki_rollback with:
- change_id: "ch-20260415-083000"
- signed_approval: {...}
- expected_base_commit: "abc789..."
- reason: "Incorrect information detected"
```

Response:
```json
{
  "status": "success",
  "rollback_change_id": "ch-20260415-083200",
  "original_change_id": "ch-20260415-083000",
  "rolled_back_at": 1713164000.123
}
```

## Common Use Cases

### Use Case 1: Ingest a New Document

```
Use wiki_ingest with:
- source_path: "/path/to/document.txt"
- agent_id: "claude-assistant"
```

This will:
1. Read the text file content
2. Create or update a wiki page based on the filename
3. Propose a patch for human review

### Use Case 2: Update Existing Knowledge

```
1. Use wiki_search to find the page
2. Use wiki_read to get current content
3. Use wiki_propose_patch to propose updates
4. Human reviews and approves
5. Use wiki_apply_patch to apply changes
```

### Use Case 3: Explore Related Concepts

```
1. Use wiki_search to find a starting point
2. Use wiki_graph_neighbors to explore connections
3. Use wiki_read to dive into specific pages
```

## Security Model

### Approval Workflow

1. **Agent proposes** → Creates patch in `.pending/`
2. **Human reviews** → Examines patch JSON file and metadata
3. **Human signs** → Generates cryptographic signature
4. **Agent applies** → Submits signed approval
5. **System verifies** → Checks signature, nonce, TOCTOU
6. **System commits** → Applies changes to git

### Security Guarantees

- **Anti-Replay**: Each signature can only be used once (nonce tracking)
- **Time-Bound**: Signatures expire after 5 minutes (configurable)
- **TOCTOU Protection**: Base commit must match expected value
- **Atomic Operations**: Nonce check and consumption are atomic
- **Audit Trail**: All operations logged with full signature
- **Note**: `wiki_resolve_conflict` currently uses metadata-only validation

### Error Handling

Common error responses:

```json
// Signature verification failed
{
  "status": "failed",
  "reason": "signature_verification_failed: nonce_already_used"
}

// Base commit changed (TOCTOU)
{
  "status": "failed",
  "reason": "base_commit_changed",
  "expected": "abc123...",
  "actual": "def456..."
}

// Unauthorized approver
{
  "status": "failed",
  "reason": "unauthorized_approver"
}
```

## Best Practices

### For AI Agents

1. **Always check status first**: Use `wiki_status` to verify wiki health
2. **Search before creating**: Use `wiki_search` to avoid duplicates
3. **Provide high confidence**: Only propose patches with confidence ≥ 0.8
4. **Include source references**: Always cite sources for traceability
5. **Handle rejections gracefully**: If approval is denied, understand why

### For Human Reviewers

1. **Review diffs carefully**: Check `.pending/` directory for patch JSON files
2. **Verify sources**: Ensure source references are valid
3. **Check confidence scores**: Low confidence may indicate uncertainty
4. **Use lint reports**: Run `wiki_lint` before approving
5. **Document rejections**: Provide clear reasons when denying patches

### For System Administrators

1. **Regular backups**: Wiki is git-based, use `git push` to backup
2. **Monitor audit logs**: Check `.audit/` for suspicious activity
3. **Rotate secrets**: Periodically update HMAC secrets in `approvers.yaml`
4. **Clean up nonces**: Old nonces are auto-cleaned per `cleanup_interval_hours`
5. **Review permissions**: Regularly audit `approvers.yaml` for access control

## Troubleshooting

### "Patch not found"

- Check if patch exists in `.pending/` directory (as `.json` file)
- Verify patch_id is correct

### "Signature verification failed"

- Check if nonce was already used (anti-replay)
- Verify signature hasn't expired (TTL)
- Ensure approver_id matches `approvers.yaml`

### "Base commit changed"

- Another change was committed between propose and apply
- Get new base commit: `git rev-parse HEAD`
- Re-sign approval with new base commit

### "Lint failed"

- Check lint report in response
- Fix errors in the proposed patch content
- Re-propose patch after fixes

## Next Steps

- **Deployment**: See [DEPLOYMENT.md](DEPLOYMENT.md) for installation
- **API Reference**: See [MCP_INTERFACE.md](MCP_INTERFACE.md) for complete API
- **Architecture**: See [ARCHITECTURE_ANALYSIS.md](ARCHITECTURE_ANALYSIS.md) for design details
- **Development**: See [DAY5_DELIVERY.md](DAY5_DELIVERY.md) for implementation notes

## Support

For issues and questions:
- Check [DEPLOYMENT.md](DEPLOYMENT.md) troubleshooting section
- Review [MCP_INTERFACE.md](MCP_INTERFACE.md) for API details
- Examine `.audit/` logs for operation history
