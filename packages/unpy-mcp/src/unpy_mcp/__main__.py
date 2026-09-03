"""npy-mcp entry point — auto-detect transport from --transport flag.

Usage:
    unpy-mcp                      # stdio (default, for local Claude Desktop)
    unpy-mcp --transport stdio    # explicit stdio
    unpy-mcp --transport http --host 0.0.0.0 --port 8000  # remote HTTP

Auth (HTTP only):
    Set NOTION_MCP_AUTH_TOKEN env var to require Bearer token auth.
    Clients must send `Authorization: Bearer <token>`.
    If unset, the HTTP server runs open (no auth) — for local testing only.
"""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(prog="unpy-mcp")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport mode (default: stdio for local, http for remote).",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host.")
    parser.add_argument("--port", type=int, default=8000, help="HTTP bind port.")
    args = parser.parse_args()

    # Ensure npy-mcp source is importable
    import os
    src_dir = os.path.dirname(__file__)
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)

    from .server import mcp

    if args.transport == "stdio":
        mcp.run()  # blocks, reads stdin/writes stdout
    else:
        from .transport_http import run_http
        run_http(mcp, host=args.host, port=args.port)


if __name__ == "__main__":
    main()