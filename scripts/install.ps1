# npy-mcp installer — Windows PowerShell
#
# Single command (run in PowerShell):
#   irm https://raw.githubusercontent.com/PigRabbBoy/npy-mcp/master/scripts/install.ps1 | iex
#
# Or with flags (non-interactive):
#   & ([scriptblock]::Create((irm https://raw.githubusercontent.com/PigRabbBoy/npy-mcp/master/scripts/install.ps1))) `
#       -Clients claude-desktop,cursor -Token "v03%3AeyJ..." -AllowWrite
#
# What it does:
#   1. Checks for uvx (installs uv if missing; uvx manages Python itself)
#   2. Asks which AI clients to install the MCP server into (multiselect)
#   3. Asks for NOTION_TOKEN_V2 / NOTION_SPACE_ID / NOTION_ALLOW_WRITE
#   4. Merges the config into each client's config file (with backup)
#
# Uninstall: irm .../uninstall.ps1 | iex

param(
  [string[]]$Clients = @(),
  [string]$Token = "",
  [string]$Space = "",
  [switch]$AllowWrite,
  [switch]$NoWrite,
  [ValidateSet("global", "project", "")]
  [string]$Scope = "",
  [switch]$Yes
)

$ErrorActionPreference = "Stop"
$RepoUrl = "git+https://github.com/PigRabbBoy/npy-mcp@v1.0.1#subdirectory=packages/unpy-mcp"
$ServerArgs = @("--refresh", "--from", $RepoUrl, "unpy-mcp")

function Say($msg)  { Write-Host "==> $msg" -ForegroundColor Cyan }
function Warn($msg) { Write-Host " !! $msg" -ForegroundColor Yellow }
function Die($msg)  { Write-Host " !! $msg" -ForegroundColor Red; exit 1 }

$nonInteractive = ($Clients.Count -gt 0) -or ($Token -ne "")

# ---------------------------------------------------------------- 1. uvx check
function Ensure-Uvx {
  $existing = Get-Command uvx -ErrorAction SilentlyContinue
  if ($existing) {
    Say "Found uvx: $($existing.Source)"
    return $existing.Source
  }
  $localUvx = "$env:USERPROFILE\.local\bin\uvx.exe"
  if (Test-Path $localUvx) {
    Say "Found uvx at $localUvx (adding to PATH)"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
    return $localUvx
  }
  if (-not $nonInteractive) {
    $answer = Read-Host "==> uvx (uv) is not installed. Install it now? [Y/n]"
    if ($answer -and $answer -notmatch '^[Yy]') {
      Die "uvx is required. Install it from https://docs.astral.sh/uv/ and re-run."
    }
  } else {
    Say "uvx not found - installing uv automatically"
  }
  Say "Installing uv (official installer)..."
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
  $cmd = Get-Command uvx -ErrorAction SilentlyContinue
  if (-not $cmd) { Die "uvx still not on PATH after install - open a new terminal and re-run." }
  Say "uv installed: $($cmd.Source)"
  return $cmd.Source
}
$UvxPath = (Ensure-Uvx) -replace '\\"', ''

# ---------------------------------------------------------------- 2. client selection
$ClientCatalog = @(
  @{ id = "claude-desktop"; label = "Claude Desktop"; dual = $false },
  @{ id = "claude-code";    label = "Claude Code";    dual = $true  },
  @{ id = "cursor";         label = "Cursor";         dual = $true  },
  @{ id = "vscode";         label = "VS Code";        dual = $false },
  @{ id = "codex";          label = "Codex CLI";      dual = $false },
  @{ id = "opencode";       label = "opencode";       dual = $false },
  @{ id = "windsurf";       label = "Windsurf";       dual = $false }
)
$AllIds = $ClientCatalog | ForEach-Object { $_.id }

function Validate-Clients {
  foreach ($chosen in $Clients) {
    if ($AllIds -notcontains $chosen) {
      Die "Unknown client '$chosen'. Valid: $($AllIds -join ', ')"
    }
  }
}

function Prompt-Clients {
  Write-Host ""
  Say "Which AI clients should get the Notion MCP server?"
  Write-Host "    1) Claude Desktop      5) Codex CLI"
  Write-Host "    2) Claude Code         6) opencode"
  Write-Host "    3) Cursor              7) Windsurf"
  Write-Host "    4) VS Code             a) all of them"
  $picks = Read-Host "    Enter numbers separated by space (e.g. 1 3 4)"
  if (-not $picks) { $picks = "a" }
  $script:Clients = @()
  if ($picks -match '^[Aa]$') {
    $script:Clients = $AllIds
  } else {
    foreach ($p in ($picks -split '\s+') | Where-Object { $_ }) {
      switch ($p) {
        "1" { $script:Clients += "claude-desktop" }
        "2" { $script:Clients += "claude-code" }
        "3" { $script:Clients += "cursor" }
        "4" { $script:Clients += "vscode" }
        "5" { $script:Clients += "codex" }
        "6" { $script:Clients += "opencode" }
        "7" { $script:Clients += "windsurf" }
        default { Warn "Ignoring '$p' (1-7 or a)" }
      }
    }
    if ($script:Clients.Count -eq 0) { Die "No client selected." }
  }
}

function Prompt-Scope($clientLabel) {
  $s = Read-Host "    Scope for $clientLabel - [G]lobal (recommended) or [p]roject? "
  if ($s -match '^[Pp]') { "project" } else { "global" }
}

# ---------------------------------------------------------------- 3. credentials
function Prompt-Credentials {
  if (-not $Token) {
    Write-Host ""
    Say "NOTION_TOKEN_V2 - your Notion session token"
    Write-Host "    How to get it:"
    Write-Host "      1. Open https://app.notion.com in Chrome (logged in)"
    Write-Host "      2. F12 -> Application tab -> Cookies -> https://app.notion.com"
    Write-Host "      3. Copy the Value of 'token_v2' (starts with v03%3A...)"
    $script:Token = Read-Host "    Paste it here"
    if (-not $script:Token) { Die "NOTION_TOKEN_V2 is required." }
  }
  if (-not $Space) {
    Write-Host ""
    Say "NOTION_SPACE_ID - optional, only if your token has multiple workspaces"
    Write-Host "    How to find it (skip with Enter to use the first space):"
    Write-Host "      - CLI: 'uv run notion auth spaces' in the repo"
    Write-Host "      - DevTools: F12 -> Network -> open a Notion page -> find api/v3/loadUserContent"
    Write-Host "        -> the key under ""space"": {...} is the ID"
    $script:Space = Read-Host "    Paste it here (Enter to skip)"
  }
  if (-not $AllowWrite -and -not $NoWrite) {
    Write-Host ""
    $aw = Read-Host "==> Enable write tools (AI can create/edit/delete pages and rows)? [y/N]"
    if ($aw -match '^[Yy]') { $script:allowWriteValue = "1" } else { $script:allowWriteValue = "0" }
  } elseif ($AllowWrite) {
    $script:allowWriteValue = "1"
  } else {
    $script:allowWriteValue = "0"
  }
}

# ---------------------------------------------------------------- 4. config merge
function Get-ClientPath($clientId, $scope) {
  $appData = $env:APPDATA
  $localAppData = $env:LOCALAPPDATA
  switch ($clientId) {
    "claude-desktop" { return "$appData\Claude\claude_desktop_config.json|global" }
    "claude-code" {
      if ($scope -eq "project" -and (Test-Path .git)) { return ".mcp.json|project" }
      return "$env:USERPROFILE\.claude.json|global"
    }
    "cursor" {
      if ($scope -eq "project" -and (Test-Path .git)) { return ".cursor\mcp.json|project" }
      return "$env:USERPROFILE\.cursor\mcp.json|global"
    }
    "vscode" {
      if ($scope -eq "project" -and (Test-Path .git)) { return ".vscode\mcp.json|project" }
      return "$appData\Code\User\mcp.json|global"
    }
    "codex"     { return "$env:USERPROFILE\.codex\config.toml|global" }
    "opencode"  { return "$env:USERPROFILE\.config\opencode\opencode.json|global" }
    "windsurf"  { return "$env:USERPROFILE\.codeium\windsurf\mcp_config.json|global" }
  }
  Die "Unknown client: $clientId"
}

function Backup-File($path) {
  if (Test-Path $path) {
    # These backups hold the token — keep only the most recent.
    Get-ChildItem "$path.bak-*" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
    Copy-Item $path "$path.bak-$(Get-Date -Format yyyyMMddHHmmss)"
  }
}

function Ensure-Gitignored($path) {
  # Keep a project-scoped, token-bearing config out of version control.
  if (-not (Test-Path .git)) { return }
  $gi = ".gitignore"
  $existing = @()
  if (Test-Path $gi) { $existing = Get-Content $gi }
  if ($existing -notcontains $path) {
    Add-Content -Path $gi -Value $path
    Say "Added '$path' to .gitignore (it contains your Notion token)"
  }
}

function New-EnvTable {
  $env2 = @{ NOTION_TOKEN_V2 = $Token }
  if ($script:allowWriteValue -eq "1") { $env2.NOTION_ALLOW_WRITE = "1" }
  if ($Space) { $env2.NOTION_SPACE_ID = $Space }
  return $env2
}

function Merge-JsonClient($client, $file) {
  $key = "mcpServers"
  if ($client -eq "vscode") { $key = "servers" }
  $dir = Split-Path $file -Parent
  if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }

  $cfg = @{}
  if (Test-Path $file) {
    try { $cfg = Get-Content $file -Raw | ConvertFrom-Json -AsHashtable } catch { $cfg = @{} }
    if (-not $cfg) { $cfg = @{} }
  }

  $entry = @{
    command = $UvxPath
    args    = @("--refresh", "--from", $RepoUrl, "unpy-mcp")
    env     = New-EnvTable
  }
  if ($key -eq "servers") { $entry.type = "stdio" }

  $servers = @{}
  if ($cfg.ContainsKey($key) -and $cfg[$key]) { $servers = $cfg[$key] }
  $existed = $servers.ContainsKey("unpy-mcp")
  $servers["unpy-mcp"] = $entry
  $cfg[$key] = $servers

  Backup-File $file
  $json = $cfg | ConvertTo-Json -Depth 10
  Set-Content -Path $file -Value $json -Encoding UTF8
  if ($existed) { "UPDATED" } else { "CREATED" }
}

function Merge-TomlClient($file) {
  $dir = Split-Path $file -Parent
  if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
  Backup-File $file

  $envTable = New-EnvTable
  $envLines = ($envTable.GetEnumerator() | ForEach-Object {
    $v = $_.Value -replace '"', '\"'
    "$($_.Key) = ""$v"""
  }) -join "`n"
  $argsLines = ($ServerArgs | ForEach-Object { '"' + ($_ -replace '"', '\"') + '"' }) -join ", "

  $block = @"

[mcp_servers.unpy-mcp]
command = "$UvxPath"
args = [$argsLines]

[mcp_servers.unpy-mcp.env]
$envLines
"@

  $existed = $false
  if (Test-Path $file) {
    $content = Get-Content $file -Raw
    if ($content -match '\[mcp_servers\.unpy-mcp\]') {
      $existed = $true
      # strip previous unpy-mcp blocks (they are ours; new block wins)
      $lines = $content -split "`r?`n"
      $out = @()
      $skip = $false
      foreach ($line in $lines) {
        if ($line -match '^\[mcp_servers\.unpy-mcp\]') { $skip = $true; continue }
        if ($skip -and $line -match '^\[') { $skip = $false }
        if (-not $skip) { $out += $line }
      }
      Set-Content -Path $file -Value ($out -join "`n") -Encoding UTF8
    }
  }
  Add-Content -Path $file -Value $block -Encoding UTF8
  if ($existed) { "UPDATED" } else { "CREATED" }
}

function Merge-OpenCodeClient($file) {
  $dir = Split-Path $file -Parent
  if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }

  $cfg = @{}
  if (Test-Path $file) {
    try { $cfg = Get-Content $file -Raw | ConvertFrom-Json -AsHashtable } catch { $cfg = @{} }
    if (-not $cfg) { $cfg = @{} }
  }

  $entry = @{
    type        = "local"
    command     = @($UvxPath) + $ServerArgs
    environment = New-EnvTable
    enabled     = $true
  }
  $mcp = @{}
  if ($cfg.ContainsKey("mcp") -and $cfg["mcp"]) { $mcp = $cfg["mcp"] }
  $existed = $mcp.ContainsKey("unpy-mcp")
  $mcp["unpy-mcp"] = $entry
  $cfg["mcp"] = $mcp

  Backup-File $file
  $json = $cfg | ConvertTo-Json -Depth 10
  Set-Content -Path $file -Value $json -Encoding UTF8
  if ($existed) { "UPDATED" } else { "CREATED" }
}

function Install-Into($client, $scope) {
  $spec = Get-ClientPath $client $scope
  $parts = $spec -split '\|'
  $path = $parts[0]; $scopeUsed = $parts[1]

  $status = switch ($client) {
    "codex"    { Merge-TomlClient $path }
    "opencode" { Merge-OpenCodeClient $path }
    default    { Merge-JsonClient $client $path }
  }
  Write-Host "  [$status] $client -> $path (scope: $scopeUsed)"
  if ($scopeUsed -eq "project") {
    Warn "Project config '$path' contains your Notion token — do not commit it."
    Ensure-Gitignored $path
  }
  return $path
}

# ---------------------------------------------------------------- run
Say "npy-mcp installer (Windows)"

if ($Clients.Count -eq 0) { Prompt-Clients }
Validate-Clients

$scopeMap = @{}
foreach ($c in $Clients) {
  $isDual = ($ClientCatalog | Where-Object { $_.id -eq $c }).dual
  if ($Scope) {
    $scopeMap[$c] = $Scope
  } elseif ($nonInteractive) {
    $scopeMap[$c] = "global"
  } elseif ($isDual) {
    $scopeMap[$c] = Prompt-Scope $c
  } else {
    $scopeMap[$c] = "global"
  }
}

Prompt-Credentials

Write-Host ""
Say "Writing configs..."
$edited = @()
foreach ($c in $Clients) {
  $edited += Install-Into $c $scopeMap[$c]
}

# ---------------------------------------------------------------- summary
Write-Host ""
Say "Done! Installed into: $($Clients -join ', ')"
Write-Host "    token:     $($Token.Substring(0, [Math]::Min(12, $Token.Length)))..."
if ($Space) { Write-Host "    space:     $Space" }
Write-Host "    write:     $(if ($script:allowWriteValue -eq "1") { "enabled" } else { "disabled (read-only)" })"
Write-Host ""
Write-Host "  Next steps:"
Write-Host "    1. Fully restart the AI client(s)"
Write-Host "    2. Test: ask your AI  ->  'search Notion for pages about project status'"
Write-Host ""
Write-Host "  Config files edited (backups saved as <file>.bak-*):"
foreach ($p in $edited) { Write-Host "      $p" }
Write-Host ""
Write-Host "  To change settings later: re-run this installer (values are updated in place)."
Write-Host "  To uninstall: irm https://raw.githubusercontent.com/PigRabbBoy/npy-mcp/master/scripts/uninstall.ps1 | iex"