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

REPO_URL="git+https://github.com/PigRabbBoy/npy-mcp@v1.0.2#subdirectory=packages/unpy-mcp"
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
SKILLS_MODE=""    # "" (ask) | all | none — install the unpy-mcp SKILL into skill-enabled clients
NONINTERACTIVE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --client)      CLIENTS+=("$2"); shift 2 ;;
    --token)       TOKEN="$2"; shift 2 ;;
    --space)       SPACE_ID="$2"; shift 2 ;;
    --allow-write) ALLOW_WRITE="1"; shift ;;
    --no-write)    ALLOW_WRITE="0"; shift ;;
    --scope)       SCOPE="$2"; shift 2 ;;
    --skills)      SKILLS_MODE="all"; shift ;;
    --no-skills)   SKILLS_MODE="none"; shift ;;
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

detect_installed() {
  # echoes 1 if the client already has a config on disk (pre-check it)
  case "$1" in
    claude-desktop)
      [[ "$(uname)" == "Darwin" && -f "$HOME/Library/Application Support/Claude/claude_desktop_config.json" ]] \
        || [[ "$(uname)" != "Darwin" && -f "${XDG_CONFIG_HOME:-$HOME/.config}/Claude/claude_desktop_config.json" ]] ;;
    claude-code)  [[ -f "$HOME/.claude.json" ]] ;;
    cursor)       [[ -f "$HOME/.cursor/mcp.json" ]] ;;
    vscode)
      [[ -f "${XDG_CONFIG_HOME:-$HOME/.config}/Code/User/mcp.json" ]] \
        || [[ "$(uname)" == "Darwin" && -f "$HOME/Library/Application Support/Code/User/mcp.json" ]] ;;
    codex)        [[ -f "$HOME/.codex/config.toml" ]] ;;
    opencode)     [[ -f "${XDG_CONFIG_HOME:-$HOME/.config}/opencode/opencode.json" ]] ;;
    windsurf)     [[ -f "$HOME/.codeium/windsurf/mcp_config.json" ]] ;;
    *) return 1 ;;
  esac
}

prompt_clients() {
  # Interactive checkbox multi-select: ↑/↓ to move, Space to toggle,
  # a to toggle all, Enter to confirm. Keys are read from /dev/tty so
  # this works under `curl | bash`. Falls back to typed numbers when
  # the terminal does not support raw reads.
  local labels=() ids=() i cursor=0 n key k2 k3 any
  for entry in "${CLIENT_CATALOG[@]}"; do
    ids+=("${entry%%|*}")
    local rest="${entry#*|}"
    labels+=("${rest%%|*}")
  done
  local n=${#ids[@]}
  local checked=()
  # pre-check clients that already have a config on disk
  for ((i = 0; i < n; i++)); do
    if detect_installed "${ids[$i]}"; then
      checked+=(1)
    else
      checked+=(0)
    fi
  done

  printf '\n'
  say "Which AI clients should get the Notion MCP server?"
  printf '    \033[2m● = detected · ↑/↓ move · Space toggle · a all · Enter confirm\033[0m\n'

  if ! exec 3< /dev/tty 2> /dev/null; then
    # no controlling terminal (CI) — default to all
    CLIENTS=("${ALL_IDS[@]}")
    return
  fi

  printf '\033[?25l'
  local first_draw=1
  while :; do
    (( first_draw )) || printf '\033[%dA' "$((n + 1))"
    first_draw=0
    for ((i = 0; i < n; i++)); do
      local mark="○" marker="  "
      [[ ${checked[$i]} -eq 1 ]] && mark="●"
      [[ $i -eq $cursor ]] && marker="❯ "
      printf '  %s %s %s\033[K\n' "$marker" "$mark" "${labels[$i]}"
    done
    printf '    a) toggle all   Enter) confirm\033[K'
    IFS= read -rsn1 key <&3 || key=""
    if [[ $key == $'\x1b' ]]; then
      read -rsn1 k2 <&3 || k2=""
      read -rsn1 k3 <&3 || k3=""
      case "$k2$k3" in
        "[A") ((cursor > 0)) && cursor=$((cursor - 1)) ;;
        "[B") ((cursor < n - 1)) && cursor=$((cursor + 1)) ;;
      esac
    elif [[ $key == " " ]]; then
      if [[ ${checked[$cursor]} -eq 1 ]]; then checked[$cursor]=0; else checked[$cursor]=1; fi
    elif [[ $key == "a" || $key == "A" ]]; then
      any=0
      for ((i = 0; i < n; i++)); do [[ ${checked[$i]} -eq 0 ]] && any=1; done
      for ((i = 0; i < n; i++)); do checked[$i]=$any; done
    elif [[ -z $key ]]; then
      break
    fi
  done
  exec 3<&-
  printf '\033[?25h\n'

  CLIENTS=()
  for ((i = 0; i < n; i++)); do
    [[ ${checked[$i]} -eq 1 ]] && CLIENTS+=("${ids[$i]}")
  done
  [[ ${#CLIENTS[@]} -gt 0 ]] || die "No client selected."
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
    "args": ["--refresh", "--from", "git+https://github.com/PigRabbBoy/npy-mcp@v1.0.2#subdirectory=packages/unpy-mcp", "unpy-mcp"],
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
    "args": ["--refresh", "--from", "git+https://github.com/PigRabbBoy/npy-mcp@v1.0.2#subdirectory=packages/unpy-mcp", "unpy-mcp"],
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
    "command": [uvx, "--refresh", "--from", "git+https://github.com/PigRabbBoy/npy-mcp@v1.0.2#subdirectory=packages/unpy-mcp", "unpy-mcp"],
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

# ---------------------------------------------------------------- 5. agent skill (optional)
# The SKILL.md teaches an agent HOW to use the MCP tools (tool selection,
# workflows, safety). Copies the bundled skill into each selected client's
# skills directory (issue: broaden client support).
SKILL_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)/../packages/unpy-mcp/skills/unpy-mcp"
[[ -d "$SKILL_SRC" ]] || SKILL_SRC=""
if [[ -z "$SKILL_SRC" ]]; then
  # running via `curl | bash` — no repo checkout; fetch the skill files
  SKILL_TMP="$(mktemp -d)/unpy-mcp"
  mkdir -p "$SKILL_TMP"
  base="https://raw.githubusercontent.com/PigRabbBoy/npy-mcp/master/packages/unpy-mcp/skills/unpy-mcp"
  if curl -fsSL "$base/SKILL.md" -o "$SKILL_TMP/SKILL.md" 2>/dev/null \
     && curl -fsSL "$base/TOOLS.md" -o "$SKILL_TMP/TOOLS.md" 2>/dev/null; then
    SKILL_SRC="$SKILL_TMP"
  else
    SKILL_SRC=""   # offline / repo unreachable — skip the skill phase
  fi
fi

SKILL_CLIENTS=()
prompt_skills() {
  echo
  say "Also install the unpy-mcp SKILL (agent instructions) into skill-enabled clients?"
  echo "    These read SKILL.md files so the agent knows which tool to use when."
  echo "    a) All supported clients (creates <dir>/skills/unpy-mcp/)"
  echo "    n) Skip — MCP config above is enough"
  printf '    [a/n]: '
  tty_read SKILLS_MODE
  SKILLS_MODE="${SKILLS_MODE:-a}"
}

if [[ -n "$SKILL_SRC" && -z "$SKILLS_MODE" && $NONINTERACTIVE -eq 0 ]]; then
  prompt_skills
fi
if [[ -n "$SKILL_SRC" && "$SKILLS_MODE" == "a" ]]; then
  # id|label|dir — dir relative to $HOME (a leading literal "~" is expanded)
  SKILL_CATALOG=(
    "aiderdesk|AiderDesk|.aider-desk/skills"
    "astrbot|AstrBot|data/skills"
    "autohand|Autohand Code CLI|.autohand/skills"
    "augment|Augment|.augment/skills"
    "bob|IBM Bob|.bob/skills"
    "claude-code|Claude Code|.claude/skills"
    "openclaw|OpenClaw|skills"
    "codearts|CodeArts Agent|.codeartsdoer/skills"
    "codebuddy|CodeBuddy|.codebuddy/skills"
    "codemaker|Codemaker|.codemaker/skills"
    "codestudio|Code Studio|.codestudio/skills"
    "commandcode|Command Code|.commandcode/skills"
    "continue|Continue|.continue/skills"
    "cortex|Cortex Code|.cortex/skills"
    "crush|Crush|.crush/skills"
    "devin|Devin for Terminal|.devin/skills"
    "droid|Droid|.factory/skills"
    "forgecode|ForgeCode|.forge/skills"
    "goose|Goose|.goose/skills"
    "grok-build|Grok Build|.grok/skills"
    "hermes|Hermes Agent|.hermes/skills"
    "inferencesh|inference.sh|.inferencesh/skills"
    "jazz|Jazz|.jazz/skills"
    "junie|Junie|.junie/skills"
    "iflow|iFlow CLI|.iflow/skills"
    "kilocode|Kilo Code|.kilocode/skills"
    "kimchi|Kimchi|.kimchi/skills"
    "kiro|Kiro CLI|.kiro/skills"
    "kode|Kode|.kode/skills"
    "lingma|Lingma|.lingma/skills"
    "mcpjam|MCPJam|.mcpjam/skills"
    "minimax|MiniMax Code|.minimax/skills"
    "mistral-vibe|Mistral Vibe|.vibe/skills"
    "moxby|Moxby|.moxby/skills"
    "mux|Mux|.mux/skills"
    "openhands|OpenHands|.openhands/skills"
    "ona|Ona|.ona/skills"
    "pi|Pi|.pi/skills"
    "posit|Posit Assistant|.posit/assistant/skills"
    "qoder|Qoder|.qoder/skills"
    "qwen-code|Qwen Code|.qwen/skills"
    "reasonix|Reasonix|.reasonix/skills"
    "rovodev|Rovo Dev|.rovodev/skills"
    "roo|Roo Code|.roo/skills"
    "tabnine|Tabnine CLI|.tabnine/agent/skills"
    "terramind|Terramind|.terramind/skills"
    "tinycloud|Tinycloud|.tinycloud/skills"
    "trae|Trae|.trae/skills"
    "windsurf-skills|Windsurf|.windsurf/skills"
    "zcode|ZCode|.zcode/skills"
    "zencoder|Zencoder|.zencoder/skills"
    "neovate|Neovate|.neovate/skills"
    "pochi|Pochi|.pochi/skills"
    "adal|AdaL|.adal/skills"
    "antigravity|Antigravity|.antigravity/skills"
    "antigravity-cli|Antigravity CLI|.antigravity/skills"
    "opencode-skills|opencode|.config/opencode/skills"
  )
  for entry in "${SKILL_CATALOG[@]}"; do
    sdir="${entry##*|}"
    target="$HOME/$sdir/unpy-mcp"
    mkdir -p "$target"
    cp -R "$SKILL_SRC"/. "$target"/
    SKILL_CLIENTS+=("$target")
  done
  say "Skill installed into ${#SKILL_CATALOG[@]} skill directories (~/*/skills/unpy-mcp)"
fi

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
[[ ${#SKILL_CLIENTS[@]:-0} -gt 0 ]] || SKILL_CLIENTS=()
if [[ ${#SKILL_CLIENTS[@]} -gt 0 ]]; then
  echo
  echo "  Skill (SKILL.md) installed into:"
  echo "      ${SKILL_CLIENTS[0]} (+$((${#SKILL_CLIENTS[@]} - 1)) more — same pattern in ~/<dir>/skills/unpy-mcp)"
fi
echo
echo "  To change settings later: re-run this installer (values are updated in place)."
echo "  To uninstall: curl -fsSL https://raw.githubusercontent.com/PigRabbBoy/npy-mcp/master/scripts/uninstall.sh | bash"