# Install the HoneyFilmmaker GUI-driven model placer.
# sfm.CreateModel() returns None in every script context, so the model is
# created through the real SFM UI flow (Animation Set Editor [+] -> Create
# Animation Set for New Model) driven with Qt.
#
# Uses a NEW filename so SFM cannot serve a cached copy of an older script.
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$Base = "D:\SteamLibrary\steamapps\common\SourceFilmmaker\game\usermod\scripts\sfm"
$Source = Join-Path $Repo "src\bridge\honey_gui_place.py"

$targets = @(
  (Join-Path $Base "mainmenu\honey_gui_v1.py"),
  (Join-Path $Base "animset\honey_gui_v1.py"),
  (Join-Path $Base "dag\exact\count1\honey_gui_v1.py")
)
foreach ($t in $targets) {
  $d = Split-Path -Parent $t
  if (!(Test-Path $d)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
  Copy-Item -LiteralPath $Source -Destination $t -Force
  Write-Host "installed -> $t"
}
# Remove the old script names so SFM cannot run the cached versions.
Get-ChildItem $Base -Recurse -Filter "honey_place_models.py" -ErrorAction SilentlyContinue |
  ForEach-Object { Remove-Item $_.FullName -Force; Write-Host "removed old -> $($_.FullName)" }
Write-Host "restart SFM to activate"
