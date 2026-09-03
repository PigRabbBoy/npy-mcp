#!/usr/bin/env bash
# npy-mcp installer — macOS + Linux
#
# Single command:
#   curl -fsSL https://raw.githubusercontent.com/PigRabbBoy/npy-mcp/master/scripts/install.sh | bash
#
# Or with flags (non-interactive):
#   curl -fsSL .../install.sh | bash -s -- \
#     --client claude-desktop --client cursor \
#     --token "v03%3AeyJ..." --space "<optional>" --allow-write
#
# What it does:
#   1. Checks for uvx (installs uv if missing; uvx manages Python itself)
#   2. Asks which AI clients to install the MCP server into (multiselect)
#   3. Asks for NOTION_TOKEN_V2 / NOTION_SPACE_ID / NOTION_ALLOW_WRITE
#   4. Merges the config into each client's config file (with backup)
#
# Uninstall: curl -fsSL .../uninstall.sh | bash

set -euo pipefail

REPO_URL="git+https://github.com/PigRabbBoy/npy-mcp@v1.0.1#subdirectory=packages/unpy-mcp"
SERVER_ARGS=(--refresh --from "$REPO_URL" unpy-mcp)

# ---------------------------------------------------------------- utilities
say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m !!\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m !!\033[0m %s\n' "$*" >&2; exit 1; }

# read from the user's terminal, not stdin — under `curl … | bash` stdin IS the
# script text, so a plain `read` would consume script lines as user input
tty_read() {
  if [[ -r /dev/tty ]]; then
    read -r "$@" < /dev/tty
  else
    read -r "$@"
  fi
}

# ---------------------------------------------------------------- flag parsing
CLIENTS=()
TOKEN=""
SPACE_ID=""
ALLOW_WRITE=""
SCOPE=""          # global|project — when set via flag, applies to all dual-scope clients
NONINTERACTIVE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --client)      CLIENTS+=("$2"); shift 2 ;;
    --token)       TOKEN="$2"; shift 2 ;;
    --space)       SPACE_ID="$2"; shift 2 ;;
    --allow-write) ALLOW_WRITE="1"; shift ;;
    --no-write)    ALLOW_WRITE="0"; shift ;;
    --scope)       SCOPE="$2"; shift 2 ;;
    -y|--yes)      NONINTERACTIVE=1; shift ;;
    *)             die "Unknown flag: $1 (see header of this script for usage)" ;;
  esac
done
[[ ${#CLIENTS[@]} -gt 0 ]] && NONINTERACTIVE=1
[[ -n "$TOKEN" ]] && NONINTERACTIVE=1

# ---------------------------------------------------------------- 1. uvx check
ensure_uvx() {
  if command -v uvx >/dev/null 2>&1; then
    say "Found uvx: $(command -v uvx)"
    return
  fi
  if [[ -x "$HOME/.local/bin/uvx" ]]; then
    say "Found uvx at ~/.local/bin/uvx (adding to PATH)"
    export PATH="$HOME/.local/bin:$PATH"
    return
  fi
  if [[ $NONINTERACTIVE -eq 1 ]]; then
    say "uvx not found — installing uv automatically"
  else
    printf '\033[1;34m==>\033[0m uvx (uv) is not installed. Install it now? [Y/n] '
    tty_read answer
    answer="${answer:-Y}"
    [[ "$answer" =~ ^[Yy] ]] || die "uvx is required. Install it from https://docs.astral.sh/uv/ and re-run."
  fi
  say "Installing uv (official installer)…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  command -v uvx >/dev/null 2>&1 || die "uvx still not on PATH after install — open a new terminal and re-run."
  say "uv installed: $(command -v uvx)"
}
ensure_uvx
UVX_PATH="$(command -v uvx)"

# python3 is used to merge JSON/TOML configs safely
ensure_python3() {
  command -v python3 >/dev/null 2>&1 && return
  say "python3 not found — installing via uv (uv can provision Python)"
  "$UVX_PATH" python install 3.12
  PY3_BIN="$(dirname "$UVX_PATH")/python3"
  [[ -x "$PY3_BIN" ]] || PY3_BIN="$(command -v python3 || true)"
  [[ -n "${PY3_BIN:-}" && -x "${PY3_BIN:-/nonexistent}" ]] || die "python3 is required but could not be provisioned."
}
ensure_python3
PYTHON3="${PY3_BIN:-python3}"

# ---------------------------------------------------------------- 2. client selection
# Each entry: id|label|dual-scope (0/1)
CLIENT_CATALOG=(
  "claude-desktop|Claude Desktop|0"
  "claude-code|Claude Code|1"
  "cursor|Cursor|1"
  "vscode|VS Code|0"
  "codex|Codex CLI|0"
  "opencode|opencode|0"
  "windsurf|Windsurf|0"
)
ALL_IDS=()
for c in "${CLIENT_CATALOG[@]}"; do ALL_IDS+=("${c%%|*}"); done

validate_clients() {
  for chosen in "$@"; do
    ok=""
    for id in "${ALL_IDS[@]}"; do [[ "$chosen" == "$id" ]] && ok=1; done
    [[ -n "$ok" ]] || die "Unknown client '$chosen'. Valid: ${ALL_IDS[*]}"
  done
}

prompt_clients() {
  echo
  say "Which AI clients should get the Notion MCP server?"
  echo "    1) Claude Desktop      5) Codex CLI"
  echo "    2) Claude Code         6) opencode"
  echo "    3) Cursor              7) Windsurf"
  echo "    4) VS Code             a) all of them"
  printf '    Enter numbers separated by space (e.g. 1 3 4): '
  tty_read picks
  picks="${picks:-a}"
  CLIENTS=()
  if [[ "$picks" =~ ^[Aa]$ ]]; then
    CLIENTS=("${ALL_IDS[@]}")
  else
    for p in $picks; do
      case "$p" in
        1) CLIENTS+=("claude-desktop") ;; 2) CLIENTS+=("claude-code") ;;
        3) CLIENTS+=("cursor") ;;        4) CLIENTS+=("vscode") ;;
        5) CLIENTS+=("codex") ;;         6) CLIENTS+=("opencode") ;;
        7) CLIENTS+=("windsurf") ;;      *) warn "Ignoring '$p' (1-7 or a)" ;;
      esac
    done
    [[ ${#CLIENTS[@]} -gt 0 ]] || die "No client selected."
  fi
}

is_dual_scope() {
  local chosen="$1" entry
  for entry in "${CLIENT_CATALOG[@]}"; do
    if [[ "${entry%%|*}" == "$chosen" ]]; then
      [[ "${entry##*|}" == "1" ]] && return 0 || return 1
    fi
  done
  return 1
}

prompt_scope() {
  # $1 = client id; sets SCOPE_DECISION for that client (global|project)
  printf '    Scope for %s — [G]lobal (recommended, works everywhere) or [p]roject (.cursor/.mcp in current folder)? ' "$1" >&2
  tty_read s
  s="${s:-G}"
  if [[ "$s" =~ ^[Pp] ]]; then
    echo "project"
  else
    echo "global"
  fi
}

# ---------------------------------------------------------------- 3. credentials
prompt_credentials() {
  if [[ -z "$TOKEN" ]]; then
    echo
    say "NOTION_TOKEN_V2 — your Notion session token"
    echo "    How to get it:"
    echo "      1. Open https://app.notion.com in Chrome (logged in)"
    echo "      2. F12 → Application tab → Cookies → https://app.notion.com"
    echo "      3. Copy the Value of 'token_v2' (starts with v03%3A...)"
    printf '    Paste it here: '
    tty_read TOKEN
    [[ -n "$TOKEN" ]] || die "NOTION_TOKEN_V2 is required."
  fi
  if [[ -z "$SPACE_ID" ]]; then
    if [[ $NONINTERACTIVE -eq 1 ]]; then
      SPACE_ID=""   # non-interactive: skip optional prompt
    else
    echo
    say "NOTION_SPACE_ID — optional, only if your token has multiple workspaces"
    echo "    How to find it (skip with Enter to use the first space):"
    echo "      • CLI:  'uv run notion auth spaces' in the repo (or any Notion MCP CLI)"
    echo "      • DevTools: F12 → Network → open a Notion page → find api/v3/loadUserContent"
    echo "        → the key under \"space\": {...} is the ID"
    printf '    Paste it here (Enter to skip): '
    tty_read SPACE_ID
    fi
  fi
  if [[ -z "$ALLOW_WRITE" ]]; then
    if [[ $NONINTERACTIVE -eq 1 ]]; then
      ALLOW_WRITE="0"
    else
    echo
    printf '\033[1;34m==>\033[0m Enable write tools (AI can create/edit/delete pages and rows)? [y/N] '
    tty_read aw
    if [[ "$aw" =~ ^[Yy] ]]; then ALLOW_WRITE="1"; else ALLOW_WRITE="0"; fi
    [[ "$ALLOW_WRITE" == "1" ]] \
      && echo "    → write tools ON  (NOTION_ALLOW_WRITE=1)" \
      || echo "    → write tools OFF (read-only; add \"NOTION_ALLOW_WRITE\": \"1\" to the config later to enable)"
    fi
  fi
}

# ---------------------------------------------------------------- 4. config merge
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"

client_paths() {
  # echoes "<config-path>|<scope-used>"
  local client="$1" scope="$2"
  case "$client" in
    claude-desktop)
      if [[ "$(uname)" == "Darwin" ]]; then
        echo "$HOME/Library/Application Support/Claude/claude_desktop_config.json|global"
      else
        echo "$CONFIG_HOME/Claude/claude_desktop_config.json|global"
      fi ;;
    claude-code)
      if [[ "$scope" == "project" && -d .git ]]; then echo ".mcp.json|project"; else echo "$HOME/.claude.json|global"; fi ;;
    cursor)
      if [[ "$scope" == "project" && -d .git ]]; then echo ".cursor/mcp.json|project"; else echo "$HOME/.cursor/mcp.json|global"; fi ;;
    vscode)
      if [[ "$scope" == "project" && -d .git ]]; then echo ".vscode/mcp.json|project"; else echo "$CONFIG_HOME/Code/User/mcp.json|global"; fi ;;
    codex)
      echo "$HOME/.codex/config.toml|global" ;;
    opencode)
      echo "$CONFIG_HOME/opencode/opencode.json|global" ;;
    windsurf)
      echo "$HOME/.codeium/windsurf/mcp_config.json|global" ;;
    *) die "Unknown client: $client" ;;
  esac
}

backup_file() {
  local f="$1"
  if [[ -f "$f" ]]; then
    # These backups hold the token — keep only the most recent, mode 0600.
    rm -f "$f".bak-* 2>/dev/null || true
    local b="$f.bak-$(date +%Y%m%d%H%M%S)"
    cp "$f" "$b"
    chmod 600 "$b" 2>/dev/null || true
  fi
  return 0
}

ensure_gitignored() {
  # Keep a project-scoped, token-bearing config out of version control.
  local path="$1"
  [[ -d .git ]] || return 0
  if ! grep -qxF "$path" .gitignore 2>/dev/null; then
    printf '%s\n' "$path" >> .gitignore
    say "Added '$path' to .gitignore (it contains your Notion token)"
  fi
}

merge_json_client() {
  # $1=client $2=config path — merges unpy-mcp entry into a JSON config
  local client="$1" file="$2"
  local key="mcpServers"
  [[ "$client" == "vscode" ]] && key="servers"
  [[ -f "$file" ]] || mkdir -p "$(dirname "$file")"
  "$PYTHON3" - "$file" "$key" "$UVX_PATH" "$TOKEN" "$SPACE_ID" "$ALLOW_WRITE" <<'PYEOF'
import json, sys
path, key, uvx, token, space, allow = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6]
try:
    with open(path) as f:
        cfg = json.load(f)
    if not isinstance(cfg, dict):
        raise ValueError("root is not an object")
except Exception:
    cfg = {}
entry = {
    "command": uvx,
    "args": ["--refresh", "--from", "git+https://github.com/PigRabbBoy/npy-mcp@v1.0.1#subdirectory=packages/unpy-mcp", "unpy-mcp"],
    "env": {"NOTION_TOKEN_V2": token},
}
if allow == "1":
    entry["env"]["NOTION_ALLOW_WRITE"] = "1"
if space:
    entry["env"]["NOTION_SPACE_ID"] = space
if key == "servers":
    entry["type"] = "stdio"
servers = cfg.setdefault(key, {})
existed = "unpy-mcp" in servers
servers["unpy-mcp"] = entry
with open(path, "w") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")
print("UPDATED" if existed else "CREATED")
PYEOF
}

merge_toml_client() {
  # Codex — TOML via python (tomllib read + manual append for write)
  local file="$1"
  [[ -f "$file" ]] || mkdir -p "$(dirname "$file")"
  backup_file "$file"
  "$PYTHON3" - "$file" "$UVX_PATH" "$TOKEN" "$SPACE_ID" "$ALLOW_WRITE" <<'PYEOF'
import sys
path, uvx, token, space, allow = sys.argv[1:6]
try:
    import tomllib
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
except Exception:
    cfg = {}
mcp = cfg.setdefault("mcp_servers", {})
existed = "unpy-mcp" in mcp
env = {"NOTION_TOKEN_V2": token}
if allow == "1":
    env["NOTION_ALLOW_WRITE"] = "1"
if space:
    env["NOTION_SPACE_ID"] = space
entry = {
    "command": uvx,
    "args": ["--refresh", "--from", "git+https://github.com/PigRabbBoy/npy-mcp@v1.0.1#subdirectory=packages/unpy-mcp", "unpy-mcp"],
    "env": env,
}
mcp["unpy-mcp"] = entry

def toml_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'

lines = []
def emit_table(name, table):
    lines.append(f"[{name}]")
    for k, v in table.items():
        if isinstance(v, dict):
            emit_table(f"{name}.{k}", v)
        elif isinstance(v, list):
            lines.append(f"{k} = [" + ", ".join(toml_str(x) for x in v) + "]")
        else:
            lines.append(f"{k} = {toml_str(v)}")
    lines.append("")

emit_table("mcp_servers.unpy-mcp", entry)
with open(path, "a") as f:
    f.write("\n" + "\n".join(lines))
print("UPDATED" if existed else "CREATED")
PYEOF
}

merge_opencode_client() {
  # opencode uses "mcp" key, flat command array, "environment"
  local file="$1"
  [[ -f "$file" ]] || mkdir -p "$(dirname "$file")"
  "$PYTHON3" - "$file" "$UVX_PATH" "$TOKEN" "$SPACE_ID" "$ALLOW_WRITE" <<'PYEOF'
import json, sys
path, uvx, token, space, allow = sys.argv[1:6]
try:
    with open(path) as f:
        cfg = json.load(f)
    if not isinstance(cfg, dict):
        raise ValueError
except Exception:
    cfg = {}
env = {"NOTION_TOKEN_V2": token}
if allow == "1":
    env["NOTION_ALLOW_WRITE"] = "1"
if space:
    env["NOTION_SPACE_ID"] = space
entry = {
    "type": "local",
    "command": [uvx, "--refresh", "--from", "git+https://github.com/PigRabbBoy/npy-mcp@v1.0.1#subdirectory=packages/unpy-mcp", "unpy-mcp"],
    "environment": env,
    "enabled": True,
}
mcp = cfg.setdefault("mcp", {})
existed = "unpy-mcp" in mcp
mcp["unpy-mcp"] = entry
with open(path, "w") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")
print("UPDATED" if existed else "CREATED")
PYEOF
}

install_into() {
  local client="$1" scope="$2"
  local spec path scope_used
  spec="$(client_paths "$client" "$scope")"
  path="${spec%%|*}"; scope_used="${spec##*|}"

  backup_file "$path"

  local status
  case "$client" in
    codex)    status="$(merge_toml_client "$path")" ;;
    opencode) status="$(merge_opencode_client "$path")" ;;
    *)        status="$(merge_json_client "$client" "$path")" ;;
  esac
  # The written config embeds NOTION_TOKEN_V2 — restrict to the current user.
  chmod 600 "$path" 2>/dev/null || true
  echo "  [$status] $client → $path (scope: $scope_used)"
  if [[ "$scope_used" == "project" ]]; then
    warn "Project config '$path' contains your Notion token — do not commit it."
    ensure_gitignored "$path"
  fi
}

# ---------------------------------------------------------------- run
say "npy-mcp installer (macOS/Linux)"

if [[ ${#CLIENTS[@]} -eq 0 ]]; then prompt_clients; fi
validate_clients "${CLIENTS[@]}"

# scope decisions stored as "client|scope" lines (portable — macOS bash 3.2 has no -A)
SCOPE_FILE="$(mktemp)"
for c in "${CLIENTS[@]}"; do
  if [[ -n "$SCOPE" ]]; then
    echo "$c|$SCOPE" >> "$SCOPE_FILE"
  elif [[ $NONINTERACTIVE -eq 1 ]]; then
    echo "$c|global" >> "$SCOPE_FILE"
  elif is_dual_scope "$c"; then
    echo "$c|$(prompt_scope "$c")" >> "$SCOPE_FILE"
  else
    echo "$c|global" >> "$SCOPE_FILE"
  fi
done

scope_for() {
  grep -m1 "^$c|" "$SCOPE_FILE" | cut -d'|' -f2
}

prompt_credentials

echo
say "Writing configs…"
for c in "${CLIENTS[@]}"; do
  install_into "$c" "$(scope_for)"
done

# ---------------------------------------------------------------- summary
echo
say "Done! Installed into: ${CLIENTS[*]}"
echo "    token:     ${TOKEN:0:12}…"
[[ -n "$SPACE_ID" ]] && echo "    space:     $SPACE_ID"
echo "    write:     $([[ "$ALLOW_WRITE" == "1" ]] && echo enabled || echo "disabled (read-only)")"
echo
echo "  Next steps:"
echo "    1. Fully restart the AI client(s) (quit from menu bar, not just close window)"
echo "    2. Test: ask your AI  →  'search Notion for pages about project status'"
echo
echo "  Config files edited (backups saved as <file>.bak-*):"
for c in "${CLIENTS[@]}"; do
  spec="$(client_paths "$c" "$(scope_for)")"
  echo "      ${spec%%|*}"
done
echo
echo "  To change settings later: re-run this installer (values are updated in place)."
echo "  To uninstall: curl -fsSL https://raw.githubusercontent.com/PigRabbBoy/npy-mcp/master/scripts/uninstall.sh | bash"