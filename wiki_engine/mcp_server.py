"""
Minimal MCP server adapter for wiki tools.

Implements a JSON-RPC subset with:
- initialize
- tools/list
- tools/call

The goal is to expose Day4 tool functions over a stable protocol boundary
without introducing extra runtime dependencies.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from wiki_engine.mcp_tools import (
    wiki_apply_patch,
    wiki_graph_neighbors,
    wiki_ingest,
    wiki_lint,
    wiki_list_conflicts,
    wiki_propose_patch,
    wiki_read,
    wiki_resolve_conflict,
    wiki_rollback,
    wiki_search,
    wiki_status,
)


JSONRPC_VERSION = "2.0"
SERVER_NAME = "micro-wiki-mcp"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2024-11-05"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]

    def to_mcp(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


TOOL_SPECS: dict[str, ToolSpec] = {
    "wiki_read": ToolSpec(
        name="wiki_read",
        description="Read a wiki page by page_id.",
        input_schema={
            "type": "object",
            "properties": {"page_id": {"type": "string"}},
            "required": ["page_id"],
            "additionalProperties": False,
        },
    ),
    "wiki_status": ToolSpec(
        name="wiki_status",
        description="Get wiki status and summary metrics.",
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    ),
    "wiki_search": ToolSpec(
        name="wiki_search",
        description="Search wiki pages by query.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1},
                "scope": {"type": "string"},  # Reserved for future use
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    "wiki_propose_patch": ToolSpec(
        name="wiki_propose_patch",
        description="Propose a patch through workflow.propose_patch().",
        input_schema={
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "operation": {"type": "string"},
                "pages": {"type": "array", "items": {"type": "string"}},
                "diff": {"type": "string"},
                "confidence": {"type": "number"},
                "sources": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["agent_id", "operation", "pages", "diff", "confidence", "sources"],
            "additionalProperties": False,
        },
    ),
    "wiki_apply_patch": ToolSpec(
        name="wiki_apply_patch",
        description="Apply an approved patch through workflow.apply_patch().",
        input_schema={
            "type": "object",
            "properties": {
                "patch_id": {"type": "string"},
                "signed_approval": {"type": "object"},
                "expected_base_commit": {"type": "string"},
            },
            "required": ["patch_id", "signed_approval", "expected_base_commit"],
            "additionalProperties": False,
        },
    ),
    "wiki_graph_neighbors": ToolSpec(
        name="wiki_graph_neighbors",
        description="Get neighboring pages in the wiki graph.",
        input_schema={
            "type": "object",
            "properties": {
                "page_id": {"type": "string"},
                "depth": {"type": "integer", "minimum": 1},
            },
            "required": ["page_id"],
            "additionalProperties": False,
        },
    ),
    "wiki_ingest": ToolSpec(
        name="wiki_ingest",
        description="Ingest a source document and propose a patch.",
        input_schema={
            "type": "object",
            "properties": {
                "source_path": {"type": "string"},
                "agent_id": {"type": "string"},
            },
            "required": ["source_path", "agent_id"],
            "additionalProperties": False,
        },
    ),
    "wiki_list_conflicts": ToolSpec(
        name="wiki_list_conflicts",
        description="List conflict records derived from pending patches.",
        input_schema={
            "type": "object",
            "properties": {"status": {"type": "string"}},
            "required": [],
            "additionalProperties": False,
        },
    ),
    "wiki_resolve_conflict": ToolSpec(
        name="wiki_resolve_conflict",
        description="Resolve a conflict and persist resolution record.",
        input_schema={
            "type": "object",
            "properties": {
                "conflict_id": {"type": "string"},
                "action": {"type": "string"},
                "resolver": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["conflict_id", "action", "resolver", "reason"],
            "additionalProperties": False,
        },
    ),
    "wiki_lint": ToolSpec(
        name="wiki_lint",
        description="Run lint checks for all/pending/recent wiki scope.",
        input_schema={
            "type": "object",
            "properties": {"scope": {"type": "string"}},
            "required": [],
            "additionalProperties": False,
        },
    ),
    "wiki_rollback": ToolSpec(
        name="wiki_rollback",
        description="Rollback a change by reverting its git commit.",
        input_schema={
            "type": "object",
            "properties": {
                "change_id": {"type": "string"},
                "signed_approval": {"type": "object"},
                "expected_base_commit": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["change_id", "signed_approval", "expected_base_commit", "reason"],
            "additionalProperties": False,
        },
    ),
}


class WikiMCPServer:
    """Protocol adapter that dispatches MCP tool calls to wiki_engine.mcp_tools."""

    def __init__(self, wiki_root: str):
        self.wiki_root = str(Path(wiki_root))
        self._tools: dict[str, Callable[..., dict[str, Any]]] = {
            "wiki_read": wiki_read,
            "wiki_status": wiki_status,
            "wiki_search": wiki_search,
            "wiki_propose_patch": wiki_propose_patch,
            "wiki_apply_patch": wiki_apply_patch,
            "wiki_graph_neighbors": wiki_graph_neighbors,
            "wiki_ingest": wiki_ingest,
            "wiki_list_conflicts": wiki_list_conflicts,
            "wiki_resolve_conflict": wiki_resolve_conflict,
            "wiki_lint": wiki_lint,
            "wiki_rollback": wiki_rollback,
        }

    def handle_request(self, request: dict[str, Any]) -> dict[str, Any]:
        request_id = request.get("id")
        method = request.get("method")

        if request.get("jsonrpc") != JSONRPC_VERSION:
            return self._error(request_id, -32600, "Invalid Request: jsonrpc must be '2.0'")

        if method == "initialize":
            return self._result(
                request_id,
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                    "capabilities": {"tools": {}},
                },
            )

        if method == "tools/list":
            tools = [spec.to_mcp() for spec in TOOL_SPECS.values()]
            return self._result(request_id, {"tools": tools})

        if method == "tools/call":
            params = request.get("params")
            if not isinstance(params, dict):
                return self._error(request_id, -32602, "Invalid params: object expected")
            name = params.get("name")
            if not isinstance(name, str):
                return self._error(request_id, -32602, "Invalid params: 'name' must be string")
            arguments = params.get("arguments", {})
            if not isinstance(arguments, dict):
                return self._error(
                    request_id, -32602, "Invalid params: 'arguments' must be object"
                )
            return self._handle_tool_call(request_id, name, arguments)

        return self._error(request_id, -32601, f"Method not found: {method}")

    def _handle_tool_call(
        self, request_id: Any, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        tool = self._tools.get(tool_name)
        if tool is None:
            return self._error(request_id, -32601, f"Unknown tool: {tool_name}")

        # Validate arguments against inputSchema
        spec = TOOL_SPECS.get(tool_name)
        if spec:
            validation_error = self._validate_arguments(arguments, spec.input_schema)
            if validation_error:
                return self._error(request_id, -32602, validation_error)

        try:
            result = tool(self.wiki_root, **arguments)
        except TypeError as exc:
            return self._error(request_id, -32602, f"Invalid params: {exc}")
        except Exception as exc:  # pragma: no cover - defensive safety path
            return self._error(request_id, -32000, f"Tool execution failed: {exc}")

        return self._result(
            request_id,
            {
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                "structuredContent": result,
            },
        )

    def _validate_arguments(self, arguments: dict[str, Any], schema: dict[str, Any]) -> str | None:
        """
        Basic JSON Schema validation for tool arguments.
        Returns error message if validation fails, None if valid.
        """
        # Check type
        if schema.get("type") != "object":
            return None  # Only validate object schemas

        properties = schema.get("properties", {})
        required = schema.get("required", [])
        additional_properties = schema.get("additionalProperties", True)

        # Check required fields
        for field in required:
            if field not in arguments:
                return f"Missing required field: '{field}'"

        # Check additional properties
        if not additional_properties:
            for field in arguments:
                if field not in properties:
                    return f"Unknown field: '{field}'"

        # Validate each field
        for field, value in arguments.items():
            if field not in properties:
                continue

            field_schema = properties[field]
            expected_type = field_schema.get("type")

            # Type validation (bool is subclass of int, must check first)
            if expected_type == "string" and not isinstance(value, str):
                return f"Field '{field}' must be string"
            elif expected_type == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
                return f"Field '{field}' must be integer"
            elif expected_type == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))):
                return f"Field '{field}' must be number"
            elif expected_type == "array" and not isinstance(value, list):
                return f"Field '{field}' must be array"
            elif expected_type == "object" and not isinstance(value, dict):
                return f"Field '{field}' must be object"

            # Minimum validation for numbers
            if expected_type in ("integer", "number") and "minimum" in field_schema:
                minimum = field_schema["minimum"]
                if value < minimum:
                    return f"Field '{field}' must be >= {minimum}"

        return None

    def _result(self, request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}

    def _error(self, request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "error": {"code": code, "message": message},
        }


def serve_stdio(server: WikiMCPServer, in_stream: Any = None, out_stream: Any = None) -> None:
    """
    Run a Content-Length framed JSON-RPC server over stdio (MCP standard).
    """
    in_stream = in_stream if in_stream is not None else sys.stdin.buffer
    out_stream = out_stream if out_stream is not None else sys.stdout.buffer

    while True:
        # Read headers until empty line
        content_length = None
        while True:
            header_line = in_stream.readline()
            if not header_line:
                return  # EOF

            header = header_line.decode('utf-8').strip()

            # Empty line marks end of headers
            if not header:
                break

            # Parse Content-Length header
            if header.startswith('Content-Length:'):
                try:
                    content_length = int(header.split(':', 1)[1].strip())
                except (ValueError, IndexError):
                    pass
            # Ignore other headers (e.g., Content-Type)

        # Must have Content-Length to proceed
        if content_length is None:
            continue

        # Read JSON body
        body_bytes = in_stream.read(content_length)
        if len(body_bytes) != content_length:
            continue

        try:
            request = json.loads(body_bytes.decode('utf-8'))
        except json.JSONDecodeError:
            response = {
                "jsonrpc": JSONRPC_VERSION,
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            }
        else:
            if not isinstance(request, dict):
                response = {
                    "jsonrpc": JSONRPC_VERSION,
                    "id": None,
                    "error": {"code": -32600, "message": "Invalid Request"},
                }
            else:
                # Skip response for notifications (no id field)
                if "id" not in request:
                    continue
                response = server.handle_request(request)

        # Write response with Content-Length framing
        response_json = json.dumps(response, ensure_ascii=False)
        response_bytes = response_json.encode('utf-8')
        out_stream.write(f'Content-Length: {len(response_bytes)}\r\n\r\n'.encode('utf-8'))
        out_stream.write(response_bytes)
        out_stream.flush()


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    wiki_root = argv[0] if argv else str(Path.cwd())
    server = WikiMCPServer(wiki_root)
    serve_stdio(server)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
