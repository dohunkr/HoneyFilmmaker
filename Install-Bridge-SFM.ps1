# Install the HoneyFilmmaker bridge as SFM's usermod startup script.
# This gives the script the real SFM context (the 'sfm' module is only fully
# functional in SFM's own startup context, not in the Script Editor).
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$Target = "D:\SteamLibrary\steamapps\common\SourceFilmmaker\game\usermod\scripts\sfm\sfm_init.py"
$Source = Join-Path $Repo "src\bridge\sfm_init_usermod.py"

if (!(Test-Path $Source)) { Write-Host "source missing: $Source"; exit 1 }
if (!(Test-Path (Split-Path -Parent $Target))) {
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Target) | Out-Null
}
Copy-Item -LiteralPath $Target -Destination "$Target.orig" -Force -ErrorAction SilentlyContinue
Copy-Item -LiteralPath $Source -Destination $Target -Force
Write-Host "installed -> $Target"
Write-Host "restart SFM to activate"
