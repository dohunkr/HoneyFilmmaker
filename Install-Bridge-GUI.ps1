# Install the HoneyFilmmaker GUI model placer.
# SFM caches the script menu at startup, so a new filename is used to defeat
# a stale cached copy. Both usermod and platform roots are covered because
# which one SFM scans is version dependent.
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$Source = Join-Path $Repo "src\bridge\honey_gui_place.py"
$InitSource = Join-Path $Repo "src\bridge\sfm_init_usermod.py"

$Game = "D:\SteamLibrary\steamapps\common\SourceFilmmaker\game"
$Roots = @(
  (Join-Path $Game "usermod\scripts\sfm"),
  (Join-Path $Game "platform\scripts\sfm")
)
$Name = "honey_gui_v2"

foreach ($base in $Roots) {
  foreach ($sub in @("mainmenu", "animset", "dag\exact\count1")) {
    $t = Join-Path $base "$sub\$Name.py"
    $d = Split-Path -Parent $t
    if (!(Test-Path $d)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
    Copy-Item -LiteralPath $Source -Destination $t -Force
    Write-Host "installed -> $t"
  }
  $init = Join-Path $base "sfm_init.py"
  if ($base -like "*usermod*") {
    Copy-Item -LiteralPath $InitSource -Destination $init -Force
    Write-Host "installed -> $init"
  }
  # remove every older honey script so a cached menu entry cannot run them
  Get-ChildItem $base -Recurse -Filter "honey*.py" -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -ne "$Name.py" } |
    ForEach-Object { Remove-Item $_.FullName -Force; Write-Host "removed -> $($_.Name)" }
}
Write-Host "restart SFM to activate"
