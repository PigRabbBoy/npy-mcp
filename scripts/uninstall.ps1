# npy-mcp uninstaller — Windows PowerShell
#
#   irm https://raw.githubusercontent.com/PigRabbBoy/npy-mcp/master/scripts/uninstall.ps1 | iex
#
# Removes the "unpy-mcp" entry from the AI clients you pick. Other MCP
# servers in the same config file are left untouched. A .bak-* backup is
# made before every write.

param(
  [string[]]$Clients = @()
)

$ErrorActionPreference = "Stop"

function Say($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

$ClientCatalog = @(
  @{ id = "claude-desktop" }, @{ id = "claude-code" }, @{ id = "cursor" },
  @{ id = "vscode" }, @{ id = "codex" }, @{ id = "opencode" }, @{ id = "windsurf" }
)
$AllIds = $ClientCatalog | ForEach-Object { $_.id }

if ($Clients.Count -eq 0) {
  Write-Host ""
  Say "Remove the Notion MCP server from which clients?"
  Write-Host "    1) Claude Desktop      5) Codex CLI"
  Write-Host "    2) Claude Code         6) opencode"
  Write-Host "    3) Cursor              7) Windsurf"
  Write-Host "    4) VS Code             a) all"
  $picks = Read-Host "    Numbers (Enter = all)"
  if (-not $picks -or $picks -match '^[Aa]$') {
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
      }
    }
  }
}

function Get-ClientPaths($clientId) {
  # returns all candidate paths (global + project)
  switch ($clientId) {
    "claude-desktop" { return @("$env:APPDATA\Claude\claude_desktop_config.json") }
    "claude-code"    { return @("$env:USERPROFILE\.claude.json", ".mcp.json") }
    "cursor"         { return @("$env:USERPROFILE\.cursor\mcp.json", ".cursor\mcp.json") }
    "vscode"         { return @("$env:APPDATA\Code\User\mcp.json", ".vscode\mcp.json") }
    "codex"          { return @("$env:USERPROFILE\.codex\config.toml") }
    "opencode"       { return @("$env:USERPROFILE\.config\opencode\opencode.json") }
    "windsurf"       { return @("$env:USERPROFILE\.codeium\windsurf\mcp_config.json") }
  }
  return @()
}

function Remove-Json($file, $key) {
  if (-not (Test-Path $file)) { return "ABSENT" }
  try { $cfg = Get-Content $file -Raw | ConvertFrom-Json -AsHashtable } catch { return "ABSENT" }
  if (-not $cfg -or -not $cfg.ContainsKey($key)) { return "ABSENT" }
  $servers = $cfg[$key]
  if (-not $servers -or -not ($servers -is [hashtable]) -or -not $servers.ContainsKey("unpy-mcp")) { return "ABSENT" }
  $servers.Remove("unpy-mcp")
  Copy-Item $file "$file.bak-$(Get-Date -Format yyyyMMddHHmmss)"
  Set-Content -Path $file -Value ($cfg | ConvertTo-Json -Depth 10) -Encoding UTF8
  return "REMOVED"
}

function Remove-Toml($file) {
  if (-not (Test-Path $file)) { return "ABSENT" }
  $content = Get-Content $file -Raw
  if ($content -notmatch '\[mcp_servers\.unpy-mcp\]') { return "ABSENT" }
  Copy-Item $file "$file.bak-$(Get-Date -Format yyyyMMddHHmmss)"
  $lines = $content -split "`r?`n"
  $out = @(); $skip = $false
  foreach ($line in $lines) {
    if ($line -match '^\[mcp_servers\.unpy-mcp\]') { $skip = $true; continue }
    if ($skip -and $line -match '^\[') { $skip = $false }
    if (-not $skip) { $out += $line }
  }
  Set-Content -Path $file -Value ($out -join "`n") -Encoding UTF8
  return "REMOVED"
}

Say "Removing unpy-mcp from configs..."
foreach ($c in $script:Clients) {
  $removedAny = $false
  foreach ($path in (Get-ClientPaths $c)) {
    if (-not (Test-Path $path)) { continue }
    $status = switch ($c) {
      "codex"    { Remove-Toml $path }
      "opencode" { Remove-Json $path "mcp" }
      "vscode"   { Remove-Json $path "servers" }
      default    { Remove-Json $path "mcpServers" }
    }
    if ($status -eq "REMOVED") { Write-Host "  [REMOVED] $path"; $removedAny = $true }
  }
  if (-not $removedAny) { Write-Host "  [ABSENT]  $c (nothing to remove)" }
}

Write-Host ""
Say "Done. Restart the affected AI client(s) to apply."