"""Token and Space resolution for single-user auth.

Resolution order (first non-empty wins):
    1. --token / --space CLI flags (passed in by caller)
    2. NOTION_TOKEN_V2 / NOTION_SPACE_ID env vars
    3. ~/.config/notion-py/config.toml (written by `notion use-space`)
    4. ~/.config/notion-py/token (plain file, mode 0600)

No browser capture — users extract token_v2 from DevTools once.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import TypedDict


CONFIG_DIR = Path(os.environ.get("NOTION_CONFIG_DIR", "~/.config/notion-py")).expanduser()
CONFIG_FILE = CONFIG_DIR / "config.toml"
TOKEN_FILE = CONFIG_DIR / "token"


class AuthConfig(TypedDict):
    """Resolved auth state — token is always present, space may be None."""

    token: str
    space_id: str | None = None


def resolve_token(
    token_arg: str | None = None,
    *,
    env_var: str = "NOTION_TOKEN_V2",
    legacy_env_var: str = "NOTION_TOKEN",
) -> str:
    """Return the first non-empty token in resolution order."""
    if token_arg:
        return token_arg
    env = os.environ.get(env_var) or os.environ.get(legacy_env_var)
    if env:
        return env
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    raise AuthError(
        "No token found. Set NOTION_TOKEN_V2 env var, pass --token, "
        f"or write token to {TOKEN_FILE} (mode 0600)."
    )


def resolve_space(space_arg: str | None = None) -> str | None:
    """Return the first non-empty space_id in resolution order, or None."""
    if space_arg:
        return space_arg
    env = os.environ.get("NOTION_SPACE_ID")
    if env:
        return env
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "rb") as f:
            data = tomllib.load(f)
        return data.get("space_id")
    return None


def save_space(space_id: str) -> None:
    """Persist space_id to config file (used by `notion use-space`)."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(f'space_id = "{space_id}"\n', encoding="utf-8")


def resolve_auth(
    token_arg: str | None = None,
    space_arg: str | None = None,
) -> AuthConfig:
    """Convenience: resolve both token and space in one call."""
    return AuthConfig(
        token=resolve_token(token_arg),
        space_id=resolve_space(space_arg),
    )


class AuthError(Exception):
    """Raised when no token can be found."""