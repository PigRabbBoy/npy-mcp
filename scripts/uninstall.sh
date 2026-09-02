#!/usr/bin/env bash
# npy-mcp uninstaller — macOS + Linux
#
#   curl -fsSL https://raw.githubusercontent.com/PigRabbBoy/npy-mcp/master/scripts/uninstall.sh | bash
#
# Removes the "notion-py" entry from the AI clients you pick. Other MCP
# servers in the same config file are left untouched. A .bak-* backup is
# made before every write.

set -euo pipefail

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m !!\033[0m %s\n' "$*" >&2; exit 1; }

CLIENTS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --client) CLIENTS+=("$2"); shift 2 ;;
    *)        die "Unknown flag: $1" ;;
  esac
done

CLIENT_CATALOG=(
  "claude-desktop|Claude Desktop"
  "claude-code|Claude Code"
  "cursor|Cursor"
  "vscode|VS Code"
  "codex|Codex CLI"
  "opencode|opencode"
  "windsurf|Windsurf"
)
ALL_IDS=()
for c in "${CLIENT_CATALOG[@]}"; do ALL_IDS+=("${c%%|*}"); done

if [[ ${#CLIENTS[@]} -eq 0 ]]; then
  echo
  say "Remove the Notion MCP server from which clients?"
  echo "    1) Claude Desktop      5) Codex CLI"
  echo "    2) Claude Code         6) opencode"
  echo "    3) Cursor              7) Windsurf"
  echo "    4) VS Code             a) all"
  printf '    Numbers (Enter = all): '
  read -r picks
  picks="${picks:-a}"
  if [[ "$picks" =~ ^[Aa]$ ]]; then
    CLIENTS=("${ALL_IDS[@]}")
  else
    for p in $picks; do
      case "$p" in
        1) CLIENTS+=("claude-desktop") ;; 2) CLIENTS+=("claude-code") ;;
        3) CLIENTS+=("cursor") ;;        4) CLIENTS+=("vscode") ;;
        5) CLIENTS+=("codex") ;;         6) CLIENTS+=("opencode") ;;
        7) CLIENTS+=("windsurf") ;;
      esac
    done
  fi
fi
[[ ${#CLIENTS[@]} -gt 0 ]] || die "No client selected."

CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"

# python3 is used to edit JSON/TOML configs safely
command -v python3 >/dev/null 2>&1 || die "python3 is required for this uninstaller (configs are edited with it)."
PYTHON3="python3"

client_paths() {
  case "$1" in
    claude-desktop)
      if [[ "$(uname)" == "Darwin" ]]; then
        echo "$HOME/Library/Application Support/Claude/claude_desktop_config.json"
      else
        echo "$CONFIG_HOME/Claude/claude_desktop_config.json"
      fi ;;
    claude-code) echo "$HOME/.claude.json|.mcp.json" ;;
    cursor)      echo "$HOME/.cursor/mcp.json|.cursor/mcp.json" ;;
    vscode)      echo "$CONFIG_HOME/Code/User/mcp.json|.vscode/mcp.json" ;;
    codex)       echo "$HOME/.codex/config.toml" ;;
    opencode)    echo "$CONFIG_HOME/opencode/opencode.json" ;;
    windsurf)    echo "$HOME/.codeium/windsurf/mcp_config.json" ;;
    *) die "Unknown client: $1" ;;
  esac
}

backup_file() {
  [[ -f "$1" ]] && cp "$1" "$1.bak-$(date +%Y%m%d%H%M%S)"
}

remove_json() {
  "$PYTHON3" - "$1" "$2" <<'PYEOF'
import json, sys
path, key = sys.argv[1], sys.argv[2]
try:
    with open(path) as f:
        cfg = json.load(f)
except Exception:
    print("SKIP"); exit()
servers = cfg.get(key)
if not isinstance(servers, dict) or "notion-py" not in servers:
    print("ABSENT"); exit()
del servers["notion-py"]
with open(path, "w") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")
print("REMOVED")
PYEOF
}

remove_toml() {
  "$PYTHON3" - "$1" <<'PYEOF'
import sys
path = sys.argv[1]
try:
    content = open(path).read()
except Exception:
    print("SKIP"); exit()
if "[mcp_servers.notion-py]" not in content:
    print("ABSENT"); exit()
lines = content.splitlines()
out, skip = [], False
for line in lines:
    if line.strip() == "[mcp_servers.notion-py]":
        skip = True; continue
    if skip and line.startswith("["):
        skip = False
    if not skip:
        out.append(line)
open(path, "w").write("\n".join(out) + "\n")
print("REMOVED")
PYEOF
}

say "Removing notion-py from configs…"
for c in "${CLIENTS[@]}"; do
  spec="$(client_paths "$c")"
  IFS='|' read -r primary fallback <<< "$spec"
  removed=0
  # try every candidate path (global + project scopes)
  for path in "$primary" $fallback; do
    [[ -n "$path" && -f "$path" ]] || continue
    backup_file "$path"
    case "$c" in
      codex)    status="$("$PYTHON3" - "$path" <<'PYEOF'
import sys
path = sys.argv[1]
try:
    content = open(path).read()
except Exception:
    print("SKIP"); exit()
if "[mcp_servers.notion-py]" not in content:
    print("ABSENT"); exit()
lines = content.splitlines()
out, skip = [], False
for line in lines:
    if line.strip() == "[mcp_servers.notion-py]":
        skip = True; continue
    if skip and line.startswith("["):
        skip = False
    if not skip:
        out.append(line)
open(path, "w").write("\n".join(out) + "\n")
print("REMOVED")
PYEOF
)" ;;
      opencode) status="$(remove_json "$path" "mcp")" ;;
      vscode)   status="$(remove_json "$path" "servers")" ;;
      *)        status="$(remove_json "$path" "mcpServers")" ;;
    esac
    [[ "$status" == "REMOVED" ]] && { echo "  [REMOVED] $path"; removed=1; }
  done
  if [[ $removed -eq 0 ]]; then echo "  [ABSENT]  $c (nothing to remove)"; fi
done

echo
say "Done. Restart the affected AI client(s) to apply."