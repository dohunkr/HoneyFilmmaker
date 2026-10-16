"""Central configuration. Stdlib only. Windows + SFM first."""
from __future__ import annotations
import os
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORKDIR = WORKSPACE_ROOT / "workdir"
DEFAULT_WORKDIR.mkdir(parents=True, exist_ok=True)

# Verified on this machine 2026-10-16:
# D:\SteamLibrary\steamapps\common\SourceFilmmaker\game\sfm.exe exists.
# Embedded Python 2.7 at game\sdktools\python\2.7\win32\python.exe
CANDIDATE_SFM_PATHS = [
    Path(r"D:\SteamLibrary\steamapps\common\SourceFilmmaker\game\sfm.exe"),
    Path(r"C:\Program Files (x86)\Steam\steamapps\common\SourceFilmmaker\game\sfm.exe"),
]
ENV_SFM_PATH = os.environ.get("HONEY_SFM_EXE", "").strip()
if ENV_SFM_PATH:
    CANDIDATE_SFM_PATHS.insert(0, Path(ENV_SFM_PATH))

CANDIDATE_GAME_DIRS = [
    Path(r"D:\SteamLibrary\steamapps\common\SourceFilmmaker\game"),
    Path(r"C:\Program Files (x86)\Steam\steamapps\common\SourceFilmmaker\game"),
]
ENV_GAME_DIR = os.environ.get("HONEY_SFM_GAME_DIR", "").strip()
if ENV_GAME_DIR:
    CANDIDATE_GAME_DIRS.insert(0, Path(ENV_GAME_DIR))

MCP_HOST = os.environ.get("HONEY_MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.environ.get("HONEY_MCP_PORT", "8765"))
BRIDGE_DIRNAME = os.environ.get("HONEY_BRIDGE_DIR", "bridge_queue")

MAX_RETRIES_DEFAULT = 3
FPS_DEFAULT = 24

ALLOWED_WORKDIR_ENV = ("HONEY_WORKDIR",)


def resolve_workdir(explicit: str | None = None) -> Path:
    raw = explicit or os.environ.get("HONEY_WORKDIR", "") or str(DEFAULT_WORKDIR)
    p = Path(raw).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def find_sfm_exe() -> Path | None:
    for c in CANDIDATE_SFM_PATHS:
        try:
            if c.is_file():
                return c
        except OSError:
            continue
    return None


def find_game_dir() -> Path | None:
    for c in CANDIDATE_GAME_DIRS:
        try:
            if c.is_dir() and (c / "sfm.exe").is_file():
                return c
        except OSError:
            continue
    # derive from exe
    exe = find_sfm_exe()
    if exe is not None:
        return exe.parent
    return None


def is_path_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False
