"""
End-to-end stdio integration tests for MCP server.

Tests verify:
1. Real stdio framing (Content-Length headers)
2. Full request-response cycle through serve_stdio
3. Security negative cases (unauthorized operations)
"""

import io
import json
import subprocess
from pathlib import Path
import pytest

from wiki_engine.mcp_server import WikiMCPServer, serve_stdio
from wiki_engine.acl import ApprovalACL


@pytest.fixture
def temp_wiki(tmp_path):
    """Create a temporary wiki structure for testing."""
    wiki_root = tmp_path / "test_wiki"
    wiki_root.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=wiki_root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=wiki_root, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=wiki_root, check=True)

    # Create directory structure
    (wiki_root / "wiki" / "concepts").mkdir(parents=True)
    (wiki_root / ".schema").mkdir(parents=True)
    (wiki_root / ".pending").mkdir(parents=True)

    # Create approval policy
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
---

Test content.
"""
    (wiki_root / "wiki" / "concepts" / "test-page.md").write_text(page_content)

    # Initial commit
    subprocess.run(["git", "add", "."], cwd=wiki_root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=wiki_root, check=True, capture_output=True)

    return str(wiki_root)


def _send_request(server: WikiMCPServer, request: dict) -> dict:
    """Helper to send a request through stdio framing and get response."""
    request_json = json.dumps(request)
    request_bytes = request_json.encode('utf-8')

    # Build framed request
    framed_request = f'Content-Length: {len(request_bytes)}\r\n\r\n'.encode('utf-8') + request_bytes

    in_stream = io.BytesIO(framed_request)
    out_stream = io.BytesIO()

    serve_stdio(server, in_stream=in_stream, out_stream=out_stream)

    output = out_stream.getvalue()

    # Parse Content-Length header
    header_end = output.find(b'\r\n\r\n')
    assert header_end > 0, "No header found in response"

    header = output[:header_end].decode('utf-8')
    assert header.startswith('Content-Length: '), f"Invalid header: {header}"

    content_length = int(header.split(':', 1)[1].strip())
    body = output[header_end + 4:header_end + 4 + content_length]

    return json.loads(body.decode('utf-8'))


def test_e2e_initialize_through_stdio(temp_wiki):
    """E2E: initialize request through real stdio framing."""
    server = WikiMCPServer(temp_wiki)
    request = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}

    response = _send_request(server, request)

    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 1
    assert "result" in response
    assert response["result"]["serverInfo"]["name"] == "micro-wiki-mcp"


def test_e2e_tools_list_through_stdio(temp_wiki):
    """E2E: tools/list request through real stdio framing."""
    server = WikiMCPServer(temp_wiki)
    request = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}

    response = _send_request(server, request)

    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 2
    assert "result" in response
    assert len(response["result"]["tools"]) == 11  # All v1 tools


def test_e2e_wiki_read_through_stdio(temp_wiki):
    """E2E: wiki_read tool call through real stdio framing."""
    server = WikiMCPServer(temp_wiki)
    request = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "wiki_read", "arguments": {"page_id": "test-page"}},
    }

    response = _send_request(server, request)

    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 3
    assert "result" in response
    structured = response["result"]["structuredContent"]
    assert structured["status"] == "success"
    assert structured["page_id"] == "test-page"


def test_e2e_wiki_propose_and_apply_through_stdio(temp_wiki):
    """E2E: Full propose + apply workflow through real stdio framing."""
    server = WikiMCPServer(temp_wiki)

    # Step 1: Propose patch
    propose_request = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "wiki_propose_patch",
            "arguments": {
                "agent_id": "agent-test",
                "operation": "create",
                "pages": ["new-page"],
                "diff": "New content",
                "confidence": 0.95,
                "sources": ["source-1"],
            },
        },
    }

    propose_response = _send_request(server, propose_request)
    assert "result" in propose_response
    structured = propose_response["result"]["structuredContent"]
    assert structured["status"] == "success"
    patch_id = structured["patch_id"]

    # Step 2: Get current commit for TOCTOU
    current_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=temp_wiki,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    # Step 3: Sign approval
    acl = ApprovalACL(f"{temp_wiki}/.schema/approvers.yaml")
    signed_approval = acl.sign_approval(
        approver_id="human-alice",
        patch_id=patch_id,
        expected_base_commit=current_commit,
    )

    # Step 4: Apply patch
    apply_request = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {
            "name": "wiki_apply_patch",
            "arguments": {
                "patch_id": patch_id,
                "signed_approval": signed_approval,
                "expected_base_commit": current_commit,
            },
        },
    }

    apply_response = _send_request(server, apply_request)
    assert "result" in apply_response
    structured = apply_response["result"]["structuredContent"]
    assert structured["status"] == "success"
    assert "change_id" in structured


def test_e2e_security_unauthorized_apply_rejected(temp_wiki):
    """E2E Security: Unauthorized apply attempt should be rejected."""
    server = WikiMCPServer(temp_wiki)

    # Step 1: Propose patch
    propose_request = {
        "jsonrpc": "2.0",
        "id": 6,
        "method": "tools/call",
        "params": {
            "name": "wiki_propose_patch",
            "arguments": {
                "agent_id": "agent-test",
                "operation": "create",
                "pages": ["security-test"],
                "diff": "Security test content",
                "confidence": 0.95,
                "sources": ["source-1"],
            },
        },
    }

    propose_response = _send_request(server, propose_request)
    structured = propose_response["result"]["structuredContent"]
    patch_id = structured["patch_id"]

    # Step 2: Try to apply with fake signature
    current_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=temp_wiki,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    fake_approval = {
        "approver_id": "human-alice",
        "patch_id": patch_id,
        "expected_base_commit": current_commit,
        "nonce": "fake-nonce",
        "timestamp": 1234567890.0,
        "signature": "fake-signature",
    }

    apply_request = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {
            "name": "wiki_apply_patch",
            "arguments": {
                "patch_id": patch_id,
                "signed_approval": fake_approval,
                "expected_base_commit": current_commit,
            },
        },
    }

    apply_response = _send_request(server, apply_request)
    structured = apply_response["result"]["structuredContent"]
    assert structured["status"] == "failed"
    assert "signature_verification_failed" in structured["reason"]


def test_e2e_security_rollback_requires_permission(temp_wiki):
    """E2E Security: Rollback should require proper permission."""
    server = WikiMCPServer(temp_wiki)

    # Create a change to rollback
    change_id = "ch-e2e-test"
    target_file = Path(temp_wiki) / "wiki" / "rollback-test.md"
    target_file.write_text("content\n", encoding="utf-8")
    subprocess.run(["git", "add", "wiki/rollback-test.md"], cwd=temp_wiki, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", f"Apply\n\nChange ID: {change_id}\n\n[human-alice🐾]"],
        cwd=temp_wiki,
        check=True,
        capture_output=True,
    )

    current_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=temp_wiki,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    # Try rollback with fake signature
    fake_approval = {
        "approver_id": "human-alice",
        "patch_id": change_id,
        "expected_base_commit": current_commit,
        "nonce": "fake-nonce",
        "timestamp": 1234567890.0,
        "signature": "fake-signature",
    }

    rollback_request = {
        "jsonrpc": "2.0",
        "id": 8,
        "method": "tools/call",
        "params": {
            "name": "wiki_rollback",
            "arguments": {
                "change_id": change_id,
                "signed_approval": fake_approval,
                "expected_base_commit": current_commit,
                "reason": "Security test",
            },
        },
    }

    rollback_response = _send_request(server, rollback_request)
    structured = rollback_response["result"]["structuredContent"]
    assert structured["status"] == "failed"
    assert "signature_verification_failed" in structured["reason"]
