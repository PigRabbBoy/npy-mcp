"""Shared client factory — resolve token + space, build NotionClient."""

from __future__ import annotations

import sys
import os

# Ensure unpy-core is importable when running from source without install
_CORE_SRC = os.path.join(os.path.dirname(__file__), "..", "..", "unpy-core", "src")
if os.path.isdir(_CORE_SRC) and _CORE_SRC not in sys.path:
    sys.path.insert(0, os.path.abspath(_CORE_SRC))

from unpy import NotionClient
from unpy.auth import AuthError, resolve_auth, resolve_space


def get_client(token_arg: str | None = None, space_arg: str | None = None) -> NotionClient:
    """Build a NotionClient from resolved auth config."""
    cfg = resolve_auth(token_arg=token_arg, space_arg=space_arg)
    client = NotionClient(token_v2=cfg["token"])
    if cfg.get("space_id"):
        try:
            client.current_space = client.get_space(cfg["space_id"])
        except Exception:
            pass
    return client