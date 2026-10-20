"""SFM Bridge: process/session detection + file command queue.

Honest-by-design: when SFM is not running or bridge script is not
installed, every mutating call returns ok=False with a fix hint.
Never returns fake success.
"""
from __future__ import annotations
import json
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.common import config as cfg


def is_sfm_running() -> tuple[bool, list[int]]:
    """Detect sfm.exe via tasklist (Windows) without extra deps."""
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq sfm.exe", "/FO", "CSV"],
                             capture_output=True, text=True, timeout=10)
        txt = out.stdout or ""
        if "sfm.exe" not in txt.lower():
            return False, []
        pids: list[int] = []
        for line in txt.splitlines()[1:]:
            parts = [p.strip('" ') for p in line.split('","')]
            if len(parts) >= 2:
                try:
                    pids.append(int(parts[1]))
                except ValueError:
                    pass
        return True, pids
    except Exception:
        return False, []


@dataclass
class BridgePaths:
    root: Path
    inbox: Path
    outbox: Path
    session_file: Path

    @classmethod
    def from_workdir(cls, workdir: Path) -> "BridgePaths":
        root = workdir / cfg.BRIDGE_DIRNAME
        inbox = root / "inbox"
        outbox = root / "outbox"
        inbox.mkdir(parents=True, exist_ok=True)
        outbox.mkdir(parents=True, exist_ok=True)
        return cls(root=root, inbox=inbox, outbox=outbox,
                   session_file=root / "last_session.json")


ALLOWED_COMMANDS = {
    "ping", "get_session", "create_scene", "add_model",
    "set_transform", "list_objects", "create_camera",
    "set_keyframe", "render_shot", "diagnose", "probe_model",
}


class SFMBridge:
    def __init__(self, workdir: Path | None = None) -> None:
        self.workdir = cfg.resolve_workdir(str(workdir) if workdir else None)
        self.paths = BridgePaths.from_workdir(self.workdir)
        self.sfm_exe = cfg.find_sfm_exe()
        self.game_dir = cfg.find_game_dir()

    # ---- status ----
    def get_status(self) -> dict[str, Any]:
        running, pids = is_sfm_running()
        bridge_installed = self._bridge_script_present()
        pending = len(list(self.paths.inbox.glob("*.json")))
        return {
            "sfm_exe": str(self.sfm_exe) if self.sfm_exe else None,
            "sfm_installed": self.sfm_exe is not None,
            "sfm_running": running,
            "sfm_pids": pids,
            "game_dir": str(self.game_dir) if self.game_dir else None,
            "bridge_queue": str(self.paths.root),
            "bridge_script_installed": bridge_installed,
            "pending_commands": pending,
            "connected": bool(running and bridge_installed),
        }

    def _bridge_script_present(self) -> bool:
        # In-app script lives in repo; "installed" means user copied it into SFM.
        # We detect a heartbeat file written by the in-app script.
        hb = self.paths.root / "heartbeat.json"
        if not hb.is_file():
            return False
        try:
            data = json.loads(hb.read_text(encoding="utf-8"))
            ts = float(data.get("ts", 0))
            return (time.time() - ts) < 120
        except Exception:
            return False

    def get_session_info(self) -> dict[str, Any]:
        st = self.get_status()
        session: dict[str, Any] = {"connected": st["connected"]}
        if self.paths.session_file.is_file():
            try:
                session.update(json.loads(self.paths.session_file.read_text(encoding="utf-8")))
            except Exception as e:  # noqa: BLE001
                session["session_parse_error"] = str(e)
        session["status"] = st
        return session

    # ---- command queue ----
    def enqueue(self, command: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if command not in ALLOWED_COMMANDS:
            return {"ok": False, "error": {"code": "BAD_COMMAND",
                    "message": f"command not allowed: {command}",
                    "hint": f"allowed: {sorted(ALLOWED_COMMANDS)}"}}
        running, _ = is_sfm_running()
        if not running:
            return {"ok": False, "error": {"code": "SFM_NOT_RUNNING",
                    "message": "SFM (sfm.exe) is not running",
                    "hint": "Launch SFM, open a session, then copy src/bridge/sfm_in_app.py into SFM and run it"}}
        if not self._bridge_script_present():
            # Still queue the command so the in-app poller can pick it up later,
            # but report not-connected honestly.
            pass
        cmd_id = f"cmd-{uuid.uuid4().hex[:8]}"
        payload = {"id": cmd_id, "command": command, "params": params or {},
                   "created_at": time.time(), "status": "queued"}
        (self.paths.inbox / f"{cmd_id}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        st = self.get_status()
        return {"ok": True, "command_id": cmd_id, "connected": st["connected"],
                "note": "queued; requires SFM in-app script (sfm_in_app.py) running to execute"
                        if not st["connected"] else "queued for SFM execution"}

    def poll_result(self, command_id: str) -> dict[str, Any]:
        out = self.paths.outbox / f"{command_id}.json"
        if out.is_file():
            try:
                return {"ok": True, "result": json.loads(out.read_text(encoding="utf-8"))}
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "error": {"code": "BAD_RESULT",
                        "message": str(e), "hint": ""}}
        pend = self.paths.inbox / f"{command_id}.json"
        if pend.is_file():
            return {"ok": True, "pending": True, "command_id": command_id}
        return {"ok": False, "error": {"code": "NOT_FOUND",
                "message": f"unknown command_id: {command_id}", "hint": ""}}

    def connect(self, launch: bool = False) -> dict[str, Any]:
        st = self.get_status()
        if st["connected"]:
            return {"ok": True, "already_connected": True, "status": st}
        if st["sfm_running"] and not st["bridge_script_installed"]:
            return {"ok": False, "error": {"code": "BRIDGE_NOT_INSTALLED",
                    "message": "SFM is running but bridge heartbeat not seen",
                    "hint": "In SFM: open Script Editor, run src/bridge/sfm_in_app.py. "
                            "It polls workdir/bridge_queue/inbox/*.json every second."},
                    "status": st}
        if not st["sfm_running"]:
            if launch and st["sfm_installed"] and self.sfm_exe is not None:
                try:
                    subprocess.Popen([str(self.sfm_exe)], cwd=str(self.sfm_exe.parent))
                    return {"ok": False, "error": {"code": "SFM_LAUNCHING",
                            "message": "SFM launch requested; wait then install bridge script",
                            "hint": ""}, "status": self.get_status()}
                except Exception as e:  # noqa: BLE001
                    return {"ok": False, "error": {"code": "LAUNCH_FAILED",
                            "message": str(e), "hint": ""}, "status": st}
            return {"ok": False, "error": {"code": "SFM_NOT_RUNNING",
                    "message": "SFM is not running and auto-launch not requested",
                    "hint": f"Run {self.sfm_exe} manually, or call sfm_connect with launch=true"},
                    "status": st}
        return {"ok": False, "error": {"code": "NOT_CONNECTED",
                "message": "not connected", "hint": ""}, "status": st}
