"""Run entry: python scripts/run_server.py [--transport http|stdio]"""
import sys
sys.path.insert(0, ".")
from src.server.mcp_server import run_http, run_stdio
import src.common.config as cfg

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--transport", default="http", choices=["http", "stdio"])
    ap.add_argument("--host", default=cfg.MCP_HOST)
    ap.add_argument("--port", type=int, default=cfg.MCP_PORT)
    ap.add_argument("--workdir", default=str(cfg.DEFAULT_WORKDIR))
    from pathlib import Path
    a = ap.parse_args()
    if a.transport == "stdio":
        run_stdio(Path(a.workdir))
    else:
        run_http(a.host, a.port, Path(a.workdir))
