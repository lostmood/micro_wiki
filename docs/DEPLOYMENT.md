# Micro Wiki MCP Server - Deployment Guide

## Overview

This guide covers deploying the Micro Wiki MCP server to Claude Desktop and other MCP-compatible clients.

## Prerequisites

- Python 3.10+
- Git
- Claude Desktop (for Claude Desktop deployment)

## Installation

### 1. Clone and Setup

```bash
git clone <repository-url>
cd micro_wiki

# Add to PYTHONPATH for development
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
```

### 2. Initialize Wiki Structure

```bash
# Create wiki directory structure
mkdir -p wiki/concepts wiki/papers wiki/threads wiki/sessions
mkdir -p .schema .pending .audit

# Initialize git repository (if not already initialized)
git init
git config user.email "your-email@example.com"
git config user.name "Your Name"
```

### 3. Configure Approval Policy

Create `.schema/approval_policy.yaml`:

```yaml
mode: manual
auto_apply_enabled: false
shadow_eval_enabled: true
confidence_usage: advisory
```

Create `.schema/approvers.yaml`:

```yaml
version: "v1"

signature:
  ttl_seconds: 300
  nonce_bits: 128
  algorithm: "hmac_sha256"
  cleanup_interval_hours: 1

authorized_approvers:
  - id: "co-creator"
    name: "Human Approver"
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
```

### 4. Initial Commit

```bash
git add .
git commit -m "Initial wiki setup"
```

## Claude Desktop Configuration

### Configuration File Location

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

### Configuration Format

Add the following to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "micro-wiki": {
      "command": "python",
      "args": [
        "-m",
        "wiki_engine.mcp_server",
        "/absolute/path/to/your/wiki/root"
      ],
      "env": {
        "PYTHONPATH": "/absolute/path/to/micro_wiki"
      }
    }
  }
}
```

**Important**: Replace `/absolute/path/to/your/wiki/root` with the actual absolute path to your wiki directory.

### Example Configuration

```json
{
  "mcpServers": {
    "micro-wiki": {
      "command": "python",
      "args": [
        "-m",
        "wiki_engine.mcp_server",
        "/home/user/projects/my_wiki"
      ],
      "env": {
        "PYTHONPATH": "/home/user/projects/micro_wiki"
      }
    }
  }
}
```

### Restart Claude Desktop

After updating the configuration:

1. Quit Claude Desktop completely
2. Restart Claude Desktop
3. The MCP server will be automatically started when Claude Desktop launches

## Verification

### Check Server Status

In Claude Desktop, you can verify the server is running by asking Claude to:

```
Use wiki_status to check the wiki status
```

Expected response:
```json
{
  "status": "success",
  "total_pages": 0,
  "pending_patches": 0,
  "last_update": "2026-04-15T...",
  "health": "healthy"
}
```

### Test Basic Operations

1. **Search** (read-only, no approval needed):
   ```
   Use wiki_search to search for "test"
   ```

2. **Read** (read-only, no approval needed):
   ```
   Use wiki_read to read page "test-page"
   ```

3. **Propose Patch** (write operation, requires approval):
   ```
   Use wiki_propose_patch to create a new page
   ```

## Troubleshooting

### Server Not Starting

1. **Check Python Path**: Ensure `python` command points to Python 3.10+
   ```bash
   python --version
   ```

2. **Check Module Installation**:
   ```bash
   python -c "import wiki_engine.mcp_server"
   ```

3. **Check Wiki Root Path**: Ensure the path in configuration is absolute and exists

4. **Check Logs**: Claude Desktop logs are typically in:
   - **macOS**: `~/Library/Logs/Claude/`
   - **Windows**: `%APPDATA%\Claude\logs\`
   - **Linux**: `~/.config/Claude/logs/`

### Permission Errors

If you see "unauthorized_approver" errors:

1. Check `.schema/approvers.yaml` exists
2. Verify `approver_id` matches the ID in `approvers.yaml`
3. Ensure the approver has the required permissions

### Git Errors

If you see git-related errors:

1. Ensure the wiki root is a git repository: `git status`
2. Ensure git user is configured:
   ```bash
   git config user.email
   git config user.name
   ```

## Security Notes

1. **Approval Required**: Most write operations require human approval via signed signatures (note: `wiki_resolve_conflict` currently uses metadata-only validation)
2. **Anti-Replay**: Each approval signature can only be used once
3. **Time-Bound**: Signatures expire after 5 minutes (configurable in `approvers.yaml`)
4. **TOCTOU Protection**: Base commit must match expected value
5. **Audit Trail**: All operations are logged in `.audit/` directory

## Advanced Configuration

### Custom Approval TTL

Edit `.schema/approvers.yaml`:

```yaml
signature:
  ttl_seconds: 600  # 10 minutes instead of default 5
```

### Multiple Approvers

Add multiple approvers with different permissions:

```yaml
authorized_approvers:
  - id: "admin"
    name: "Admin User"
    role: "admin"
    auth_method: "session_identity"
    permissions: ["approve_all"]

  - id: "reviewer"
    name: "Reviewer User"
    role: "reviewer"
    auth_method: "session_identity"
    permissions: ["approve_updates"]

operation_permissions:
  approve_all:
    - "*"
  approve_updates:
    - "create"
    - "update"
```

## Next Steps

- See [QUICKSTART.md](QUICKSTART.md) for usage examples
- See [MCP_INTERFACE.md](MCP_INTERFACE.md) for complete API reference
- See [ARCHITECTURE_ANALYSIS.md](ARCHITECTURE_ANALYSIS.md) for system design details
