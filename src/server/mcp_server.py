"""MCP server: stdio (JSON-RPC) + local HTTP. Localhost only by default."""
from __future__ import annotations
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from src.common import config as cfg
from src.server.tools import ToolRegistry


def build_registry(workdir: Path | None = None) -> ToolRegistry:
    return ToolRegistry(workdir)


def handle_message(reg: ToolRegistry, msg: dict) -> dict | None:
    method = msg.get("method")
    mid = msg.get("id")
    params = msg.get("params", {})

    def _resp(result=None, error=None):
        r: dict = {"jsonrpc": "2.0", "id": mid}
        if error is not None:
            r["error"] = error
        else:
            r["result"] = result
        return r

    if method == "initialize":
        return _resp({"protocolVersion": "2024-11-05",
                      "serverInfo": {"name": "honey-filmmaker-sfm", "version": "0.1.0"},
                      "capabilities": {"tools": {}}})
    if method == "tools/list":
        return _resp({"tools": [
            {"name": t["name"], "description": t["description"],
             "inputSchema": t["inputSchema"]} for t in reg.spec_list()]})
    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        out = reg.call(name, args)
        # MCP content envelope, keep full result for debugging
        return _resp({"content": [{"type": "text",
                                   "text": json.dumps(out, ensure_ascii=False)}],
                      "isError": not out.get("ok", False)})
    if method in ("ping", "notifications/initialized"):
        return _resp({}) if mid is not None else None
    if mid is not None:
        return _resp(error={"code": -32601, "message": f"unknown method {method}"})
    return None


def run_stdio(workdir: Path | None = None) -> None:
    reg = build_registry(workdir)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        resp = handle_message(reg, msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


class Handler(BaseHTTPRequestHandler):
    registry: ToolRegistry | None = None

    def log_message(self, *a):  # quiet
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            st = self.registry.bridge.get_status() if self.registry else {}
            self._send({"ok": True, "status": st})
        elif self.path == "/tools":
            self._send({"tools": self.registry.spec_list() if self.registry else []})
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self):
        if self.path not in ("/mcp", "/tools/call"):
            self._send({"error": "not found"}, 404)
            return
        try:
            n = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except Exception as e:  # noqa: BLE001
            self._send({"ok": False, "error": str(e)}, 400)
            return
        # Accept both MCP envelope and plain {tool, args}
        if "method" in body:
            resp = handle_message(self.registry, body)
            self._send(resp or {})
        else:
            out = self.registry.call(body.get("tool", ""), body.get("args", {}))
            self._send(out)


def run_http(host: str | None = None, port: int | None = None,
             workdir: Path | None = None) -> None:
    host = host or cfg.MCP_HOST
    port = port or cfg.MCP_PORT
    # Local-only guard: refuse non-loopback bind unless explicitly allowed
    if host not in ("127.0.0.1", "localhost", "::1") and not cfg.MCP_HOST.startswith("0"):
        print(f"[mcp] refusing non-loopback bind host={host} (local-only default)",
              file=sys.stderr)
        host = "127.0.0.1"
    Handler.registry = build_registry(workdir)
    srv = HTTPServer((host, port), Handler)
    print(f"[mcp] HoneyFilmmaker MCP on http://{host}:{port} (local-only)")
    print(f"[mcp] health: http://{host}:{port}/health  tools: /tools  call: POST /mcp")
    srv.serve_forever()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--transport", choices=["stdio", "http"], default="http")
    ap.add_argument("--host", default=cfg.MCP_HOST)
    ap.add_argument("--port", type=int, default=cfg.MCP_PORT)
    ap.add_argument("--workdir", default=str(cfg.DEFAULT_WORKDIR))
    args = ap.parse_args()
    if args.transport == "stdio":
        run_stdio(Path(args.workdir))
    else:
        run_http(args.host, args.port, Path(args.workdir))
