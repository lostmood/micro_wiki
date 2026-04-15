"""
Contract tests for MCP server adapter.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest

from wiki_engine.mcp_server import TOOL_SPECS, WikiMCPServer, serve_stdio


@pytest.fixture
def temp_wiki(tmp_path):
    wiki_root = tmp_path / "test_wiki_server"
    wiki_root.mkdir()

    os.system(
        f"cd {wiki_root} && git init && git config user.email 'test@test.com' "
        "&& git config user.name 'Test'"
    )

    (wiki_root / "wiki").mkdir()
    (wiki_root / "wiki" / "concepts").mkdir()
    (wiki_root / ".pending").mkdir()
    (wiki_root / ".audit").mkdir()
    (wiki_root / ".schema").mkdir()

    (wiki_root / ".schema" / "approval_policy.yaml").write_text(
        """
mode: manual
auto_apply_enabled: false
shadow_eval_enabled: true
""",
        encoding="utf-8",
    )
    (wiki_root / ".schema" / "approvers.yaml").write_text(
        """
version: "v1"
signature:
  ttl_seconds: 300
  nonce_bits: 128
  algorithm: "hmac_sha256"
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
""",
        encoding="utf-8",
    )

    (wiki_root / "wiki" / "concepts" / "test-page.md").write_text(
        """---
page_id: test-page
title: Test Page
updated: 1234567890.0
confidence: 0.95
source_refs: [source-1]
---
Body.
""",
        encoding="utf-8",
    )

    os.system(f"cd {wiki_root} && git add -A && git commit -m 'Initial commit'")
    return str(wiki_root)


def test_initialize_returns_capabilities(temp_wiki):
    server = WikiMCPServer(temp_wiki)
    req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    resp = server.handle_request(req)

    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    assert "result" in resp
    assert resp["result"]["capabilities"] == {"tools": {}}
    assert resp["result"]["serverInfo"]["name"] == "micro-wiki-mcp"


def test_tools_list_contains_all_day4_tools(temp_wiki):
    server = WikiMCPServer(temp_wiki)
    req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    resp = server.handle_request(req)

    tools = resp["result"]["tools"]
    names = {t["name"] for t in tools}
    assert names == set(TOOL_SPECS.keys())
    assert len(names) == 5


def test_tools_call_wiki_read_success(temp_wiki):
    server = WikiMCPServer(temp_wiki)
    req = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "wiki_read", "arguments": {"page_id": "test-page"}},
    }
    resp = server.handle_request(req)

    assert "result" in resp
    structured = resp["result"]["structuredContent"]
    assert structured["status"] == "success"
    assert structured["page_id"] == "test-page"


def test_tools_call_unknown_tool_returns_error(temp_wiki):
    server = WikiMCPServer(temp_wiki)
    req = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {"name": "wiki_unknown", "arguments": {}},
    }
    resp = server.handle_request(req)

    assert "error" in resp
    assert resp["error"]["code"] == -32601
    assert "Unknown tool" in resp["error"]["message"]


def test_tools_call_invalid_arguments_type_returns_error(temp_wiki):
    server = WikiMCPServer(temp_wiki)
    req = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {"name": "wiki_read", "arguments": "not-an-object"},
    }
    resp = server.handle_request(req)

    assert "error" in resp
    assert resp["error"]["code"] == -32602


def test_serve_stdio_handles_parse_error_and_valid_request(temp_wiki):
    """Test that malformed JSON body returns -32700 and valid requests succeed."""
    server = WikiMCPServer(temp_wiki)

    # Malformed JSON with valid Content-Length framing
    invalid_json = b"not-valid-json"
    invalid_framed = f'Content-Length: {len(invalid_json)}\r\n\r\n'.encode('utf-8') + invalid_json

    # Valid framed request
    valid_request = {"jsonrpc": "2.0", "id": 6, "method": "tools/list", "params": {}}
    valid_json = json.dumps(valid_request).encode('utf-8')
    valid_framed = f'Content-Length: {len(valid_json)}\r\n\r\n'.encode('utf-8') + valid_json

    in_stream = io.BytesIO(invalid_framed + valid_framed)
    out_stream = io.BytesIO()

    serve_stdio(server, in_stream=in_stream, out_stream=out_stream)

    output = out_stream.getvalue()

    # Parse first response (parse error)
    first_header_end = output.find(b'\r\n\r\n')
    first_length = int(output[:first_header_end].decode('utf-8').split(':', 1)[1].strip())
    first_body = output[first_header_end + 4:first_header_end + 4 + first_length]
    first_response = json.loads(first_body.decode('utf-8'))

    # Parse second response (success)
    second_start = first_header_end + 4 + first_length
    second_header_end = output.find(b'\r\n\r\n', second_start)
    second_length = int(output[second_start:second_header_end].decode('utf-8').split(':', 1)[1].strip())
    second_body = output[second_header_end + 4:second_header_end + 4 + second_length]
    second_response = json.loads(second_body.decode('utf-8'))

    assert first_response["error"]["code"] == -32700
    assert "result" in second_response
    assert len(second_response["result"]["tools"]) == 5


def test_serve_stdio_with_content_length_framing(temp_wiki):
    """Test P0-1: MCP standard Content-Length framing."""
    server = WikiMCPServer(temp_wiki)

    request = {"jsonrpc": "2.0", "id": 7, "method": "tools/list", "params": {}}
    request_json = json.dumps(request)
    request_bytes = request_json.encode('utf-8')

    # Build framed request
    framed_request = f'Content-Length: {len(request_bytes)}\r\n\r\n'.encode('utf-8') + request_bytes

    in_stream = io.BytesIO(framed_request)
    out_stream = io.BytesIO()

    # Read one request and stop
    serve_stdio(server, in_stream=in_stream, out_stream=out_stream)

    output = out_stream.getvalue()

    # Parse Content-Length header
    header_end = output.find(b'\r\n\r\n')
    assert header_end > 0

    header = output[:header_end].decode('utf-8')
    assert header.startswith('Content-Length: ')

    content_length = int(header.split(':', 1)[1].strip())
    body = output[header_end + 4:header_end + 4 + content_length]

    response = json.loads(body.decode('utf-8'))
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 7
    assert "result" in response
    assert len(response["result"]["tools"]) == 5


def test_tools_call_validates_minimum_constraint(temp_wiki):
    """Test P0-2: Parameter validation for limit < 1 returns -32602."""
    server = WikiMCPServer(temp_wiki)
    req = {
        "jsonrpc": "2.0",
        "id": 8,
        "method": "tools/call",
        "params": {"name": "wiki_search", "arguments": {"query": "test", "limit": 0}},
    }
    resp = server.handle_request(req)

    assert "error" in resp
    assert resp["error"]["code"] == -32602
    assert "limit" in resp["error"]["message"]
    assert ">= 1" in resp["error"]["message"]


def test_serve_stdio_notification_no_response(temp_wiki):
    """Test P0-2: Notifications (no id field) should not produce a response."""
    server = WikiMCPServer(temp_wiki)

    # Notification (no id field)
    notification = {"jsonrpc": "2.0", "method": "tools/list", "params": {}}
    notification_json = json.dumps(notification)
    notification_bytes = notification_json.encode('utf-8')

    framed_notification = f'Content-Length: {len(notification_bytes)}\r\n\r\n'.encode('utf-8') + notification_bytes

    in_stream = io.BytesIO(framed_notification)
    out_stream = io.BytesIO()

    serve_stdio(server, in_stream=in_stream, out_stream=out_stream)

    # Should produce no output for notification
    output = out_stream.getvalue()
    assert len(output) == 0
