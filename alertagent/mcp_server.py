"""A minimal MCP server (JSON-RPC 2.0 over stdio, one message per line) for the 7 data tools.

    python3 -m alertagent.mcp_server

Supports initialize, tools/list, tools/call and ping. Any MCP client can list the
tools and call them against the mock bank. Standard library only.
"""

import json
import sys

from .bank import Bank
from .tools import DATA_TOOLS, call_tool

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "mock-bank-investigation-tools", "version": "0.1.0"}


def handle(msg, bank):
    """Returns the response dict, or None for notifications."""
    mid = msg.get("id")
    method = msg.get("method")
    if mid is None:
        return None  # notification, for example notifications/initialized
    if method == "initialize":
        result = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {"listChanged": False}}, "serverInfo": SERVER_INFO}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": DATA_TOOLS}
    elif method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        if name not in {t["name"] for t in DATA_TOOLS}:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "Unknown tool: %s" % name}}
        data, is_err = call_tool(bank, name, params.get("arguments") or {})
        result = {"content": [{"type": "text", "text": json.dumps(data)}], "structuredContent": data, "isError": is_err}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found: %s" % method}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def serve(stdin=sys.stdin, stdout=sys.stdout, bank=None):
    bank = bank or Bank()
    for raw in stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except ValueError:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            resp = handle(msg, bank)
        if resp is not None:
            stdout.write(json.dumps(resp) + "\n")
            stdout.flush()


if __name__ == "__main__":
    serve()
