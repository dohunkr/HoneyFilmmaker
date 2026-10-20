# Install the HoneyFilmmaker DAG-context script.
# The dag context is required: SFM's CreateModel only returns a model there.
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$Base = "D:\SteamLibrary\steamapps\common\SourceFilmmaker\game\usermod\scripts\sfm"
$Target = Join-Path $Base "dag\exact\count1\honey_place_models.py"
$Source = Join-Path $Repo "src\bridge\honey_place_models_dag.py"

if (!(Test-Path $Source)) { Write-Host "source missing: $Source"; exit 1 }
foreach ($d in @($Base, (Split-Path -Parent $Target))) {
  if (!(Test-Path $d)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
}
Copy-Item -LiteralPath $Source -Destination $Target -Force
Write-Host "installed -> $Target"
Write-Host ""
Write-Host "HOW TO USE (no auto-run in this context):"
Write-Host "  1. In SFM, select exactly ONE dag node (or a shot element)"
Write-Host "  2. Right-click it -> Scripts -> honey_place_models"
Write-Host "  3. The queued models are placed and the session is saved."
