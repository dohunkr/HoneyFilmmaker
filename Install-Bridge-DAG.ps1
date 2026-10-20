# Install the HoneyFilmmaker DAG + ANIMSET context scripts.
# These contexts are required: SFM's CreateModel only returns a model when the
# script runs from the dag/animset right-click menu, not from the global
# sfm_init.py context or the Script Editor.
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$Base = "D:\SteamLibrary\steamapps\common\SourceFilmmaker\game\usermod\scripts\sfm"
$Source = Join-Path $Repo "src\bridge\honey_place_models_dag.py"

$targets = @(
  (Join-Path $Base "dag\exact\count1\honey_place_models.py"),
  (Join-Path $Base "animset\honey_place_models.py"),
  (Join-Path $Base "mainmenu\honey_place_models.py")
)

foreach ($t in $targets) {
  $d = Split-Path -Parent $t
  if (!(Test-Path $d)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
  Copy-Item -LiteralPath $Source -Destination $t -Force
  Write-Host "installed -> $t"
}

Write-Host ""
Write-Host "HOW TO RUN (pick one):"
Write-Host "  A) Element Viewer tab (top-left, next to 'Animation Set Editor')"
Write-Host "     -> expand the session tree -> right-click any element"
Write-Host "     -> Scripts -> honey_place_models"
Write-Host "  B) Animation Set Editor -> right-click a set -> Scripts -> honey_place_models"
Write-Host "  C) Main Menu -> Scripts -> honey_place_models"
Write-Host ""
Write-Host "The queued models (SEORIN / IMUGYEOM / MUMYEONG) are placed on run."
