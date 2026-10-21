# Install the HoneyFilmmaker bridge into every SFM script root.
#
# Verified from ifm.dll strings:
#   "Couldn't load user initialization python script file '%s'"
#       -> scripts\sfm\sfm_init_local.py
#   "-sfm_startup_script"
#       -> explicit startup script override
#   "Couldn't load initialization python script file '%s'" + "PLATFORM"
#       -> <PLATFORM>\scripts\sfm\sfm_init.py
#
# PLATFORM is the active game module, which is why installing into a single
# root silently did nothing. Install everywhere.
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$Source = Join-Path $Repo "src\bridge\sfm_init_usermod.py"
$Game = "D:\SteamLibrary\steamapps\common\SourceFilmmaker\game"

$roots = @()
foreach ($m in @("platform", "usermod", "tf", "tf_movies", "hl2",
                 "left4dead2_movies", "workshop")) {
  $roots += (Join-Path $Game "$m\scripts\sfm")
}

foreach ($base in $roots) {
  $init = Join-Path $base "sfm_init.py"
  $d = Split-Path -Parent $init
  if (!(Test-Path $d)) { continue }
  Copy-Item -LiteralPath $init -Destination "$init.orig" -Force -ErrorAction SilentlyContinue
  Copy-Item -LiteralPath $Source -Destination $init -Force
  Write-Host "installed -> $init"
  # also provide sfm_init_local.py (highest priority per the engine strings)
  $local = Join-Path $base "sfm_init_local.py"
  Copy-Item -LiteralPath $Source -Destination $local -Force
  Write-Host "installed -> $local"
}
Write-Host "restart SFM to activate"
