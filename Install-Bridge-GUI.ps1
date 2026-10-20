# Install the HoneyFilmmaker GUI-driven model placer.
# sfm.CreateModel() returns None in every script context, so the model is
# created through the real SFM UI flow (Animation Set Editor [+] -> Create
# Animation Set for New Model) driven with Qt.
#
# Installed into BOTH usermod and platform script roots: which one SFM
# actually scans is version dependent, and guessing wrong silently runs a
# stale script.
#
# New filename (honey_gui_v1) so a cached script menu cannot serve an old
# version.
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$Source = Join-Path $Repo "src\bridge\honey_gui_place.py"
$InitSource = Join-Path $Repo "src\bridge\sfm_init_usermod.py"

$Game = "D:\SteamLibrary\steamapps\common\SourceFilmmaker\game"
$Roots = @(
  (Join-Path $Game "usermod\scripts\sfm"),
  (Join-Path $Game "platform\scripts\sfm")
)

foreach ($base in $Roots) {
  $targets = @(
    (Join-Path $base "mainmenu\honey_gui_v1.py"),
    (Join-Path $base "animset\honey_gui_v1.py"),
    (Join-Path $base "dag\exact\count1\honey_gui_v1.py")
  )
  foreach ($t in $targets) {
    $d = Split-Path -Parent $t
    if (!(Test-Path $d)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
    Copy-Item -LiteralPath $Source -Destination $t -Force
    Write-Host "installed -> $t"
  }
  # startup script (only meaningful in usermod, harmless elsewhere)
  $init = Join-Path $base "sfm_init.py"
  if ($base -like "*usermod*") {
    Copy-Item -LiteralPath $InitSource -Destination $init -Force
    Write-Host "installed -> $init"
  }
  # remove stale copies of every earlier version
  Get-ChildItem $base -Recurse -Filter "honey_place_models.py" -ErrorAction SilentlyContinue |
    ForEach-Object { Remove-Item $_.FullName -Force; Write-Host "removed old -> $($_.Name)" }
}
Write-Host "restart SFM to activate"
