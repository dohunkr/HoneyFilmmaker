# HoneyFilmmaker MCP 자동 연결 (오픈코드 + 안티그래비티)
# Setup-MCP.bat가 이 파일을 관리자권한 없이 실행합니다.
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$Wrapper = Join-Path $Repo "MCP-stdio.bat"

function Merge-McpFile($Path, $ServerKey, $Entry) {
  $dir = Split-Path -Parent $Path
  if (!(Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
  $cfg = @{}
  if (Test-Path $Path) {
    try { $cfg = Get-Content $Path -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable }
    catch {
      Copy-Item $Path "$Path.bak" -Force
      Write-Host "  기존 파일 형식이 달라 백업 후 새로 만듭니다: $Path.bak"
      $cfg = @{}
    }
  }
  if ($ServerKey -eq "mcp") {
    if (-not $cfg.ContainsKey("mcp") -or $null -eq $cfg["mcp"]) { $cfg["mcp"] = @{} }
    $cfg["mcp"]["honey-filmmaker-sfm"] = $Entry
  } else {
    if (-not $cfg.ContainsKey("mcpServers") -or $null -eq $cfg["mcpServers"]) { $cfg["mcpServers"] = @{} }
    $cfg["mcpServers"]["honey-filmmaker-sfm"] = $Entry
  }
  $cfg | ConvertTo-Json -Depth 20 | Set-Content $Path -Encoding UTF8
  Write-Host "  저장됨: $Path"
}

Write-Host "== HoneyFilmmaker MCP 연결 =="
Write-Host "  위치: $Repo"
Write-Host ""

# 1. 오픈코드 (opencode.json에 mcp 항목 병합)
$opencode = Join-Path $env:USERPROFILE ".config\opencode\opencode.json"
$openEntry = @{
  type = "local"
  command = @("cmd", "/c", $Wrapper)
  enabled = $true
}
try {
  Merge-McpFile $opencode "mcp" $openEntry
  Write-Host "  오픈코드 연결 OK (재시작하면 적용됨)"
} catch { Write-Host "  오픈코드 연결 실패: $($_.Exception.Message)" }

# 2. 안티그래비티/Claude호환 (mcpServers 형식 파일 생성 + 기존 파일 있으면 병합)
$agEntry = @{ command = $Wrapper; args = @() }
$repoAg = Join-Path $Repo "mcp_antigravity.json"
@{ mcpServers = @{ "honey-filmmaker-sfm" = $agEntry } } |
  ConvertTo-Json -Depth 20 | Set-Content $repoAg -Encoding UTF8
Write-Host "  안티그래비티용 파일 생성: mcp_antigravity.json"
foreach ($cand in @(
  (Join-Path $env:APPDATA "Antigravity\mcp_config.json"),
  (Join-Path $env:USERPROFILE ".config\antigravity\mcp.json")
)) {
  if (Test-Path (Split-Path -Parent $cand)) {
    try { Merge-McpFile $cand "mcpServers" $agEntry } catch {}
  }
}

Write-Host ""
Write-Host "완료! 오픈코드/안티그래비티를 재시작하면 'honey-filmmaker-sfm' 도구가 보입니다."
Write-Host "연결 확인: Start-HoneyFilmmaker.bat로 서버를 켜고 http://127.0.0.1:8765/health 접속"
