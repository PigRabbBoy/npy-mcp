#!/usr/bin/env bash
# npy-mcp uninstaller — macOS + Linux
#
#   curl -fsSL https://raw.githubusercontent.com/PigRabbBoy/npy-mcp/master/scripts/uninstall.sh | bash
#
# Removes the "unpy-mcp" entry from the AI clients you pick. Other MCP
# servers in the same config file are left untouched. A .bak-* backup is
# made before every write.

# read from the user's terminal, not stdin — under `curl … | bash` stdin IS the
# script text, so a plain `read` would consume script lines as user input
tty_read() {
  if [[ -r /dev/tty ]]; then
    read -r "$@" < /dev/tty
  else
    read -r "$@"
  fi
}
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
  # checkbox multiselect — same UX as the installer (↑/↓ move, Space toggle,
  # a all, Enter confirm; Enter with nothing selected = all)
  labels=() i cursor=0 key k2 k3 any
  for entry in "${CLIENT_CATALOG[@]}"; do
    rest="${entry#*|}"
    labels+=("$rest")
  done
  n=${#labels[@]}
  checked=()
  for ((i = 0; i < n; i++)); do checked+=(1); done   # default: all checked

  printf '\n'
  say "Remove the Notion MCP server from which clients?"
  printf '    \033[2m↑/↓ move · Space toggle · a all · Enter confirm\033[0m\n'

  if exec 3< /dev/tty 2> /dev/null; then
    printf '\033[?25l'
    first_draw=1
    while :; do
      (( first_draw )) || printf '\033[%dA' "$((n + 1))"
      first_draw=0
      for ((i = 0; i < n; i++)); do
        mark="○"; marker="  "
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
  else
    tty_read picks
    picks="${picks:-a}"
    if [[ "$picks" =~ ^[Aa]$ ]]; then
      checked=()
      for ((i = 0; i < n; i++)); do checked+=(1); done
    else
      checked=()
      for ((i = 0; i < n; i++)); do checked+=(0); done
      for p in $picks; do
        case "$p" in
          1) checked[0]=1 ;; 2) checked[1]=1 ;; 3) checked[2]=1 ;; 4) checked[3]=1 ;;
          5) checked[4]=1 ;; 6) checked[5]=1 ;; 7) checked[6]=1 ;;
        esac
      done
    fi
  fi

  CLIENTS=()
  for ((i = 0; i < n; i++)); do
    [[ ${checked[$i]} -eq 1 ]] && CLIENTS+=("${ALL_IDS[$i]}")
  done
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
if not isinstance(servers, dict) or "unpy-mcp" not in servers:
    print("ABSENT"); exit()
del servers["unpy-mcp"]
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
if "[mcp_servers.unpy-mcp]" not in content:
    print("ABSENT"); exit()
lines = content.splitlines()
out, skip = [], False
for line in lines:
    if line.strip() == "[mcp_servers.unpy-mcp]":
        skip = True; continue
    if skip and line.startswith("["):
        skip = False
    if not skip:
        out.append(line)
open(path, "w").write("\n".join(out) + "\n")
print("REMOVED")
PYEOF
}

say "Removing unpy-mcp from configs…"
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
if "[mcp_servers.unpy-mcp]" not in content:
    print("ABSENT"); exit()
lines = content.splitlines()
out, skip = [], False
for line in lines:
    if line.strip() == "[mcp_servers.unpy-mcp]":
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