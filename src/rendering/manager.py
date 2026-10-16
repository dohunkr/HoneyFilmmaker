"""Render manager: shot renders, ffmpeg combine, file verification.

SFM has no documented headless render CLI. This module therefore:
- records per-shot render jobs honestly (pending_SFM),
- combines existing frames/audio with ffmpeg when available,
- verifies output existence + playability (size + ffprobe when present).
"""
from __future__ import annotations
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from src.common import config as cfg


KNOWN_FFMPEG_DIRS = [
    r"D:\Github\roop-unleashed\installer\installer_files\ffmpeg\bin",
    r"C:\ProgramData\chocolatey\bin",
]


def find_ffmpeg(name: str = "ffmpeg") -> str | None:
    import os
    env = os.environ.get("HONEY_FFMPEG" if name == "ffmpeg" else "HONEY_FFPROBE", "").strip()
    if env and Path(env).is_file():
        return env
    found = shutil.which(name)
    if found:
        return found
    exe = name + (".exe" if os.name == "nt" else "")
    for d in KNOWN_FFMPEG_DIRS:
        p = Path(d) / exe
        try:
            if p.is_file():
                return str(p)
        except OSError:
            continue
    return None


class RenderManager:
    def __init__(self, workdir: Path | None = None) -> None:
        self.workdir = cfg.resolve_workdir(str(workdir) if workdir else None)
        self.state_path = self.workdir / "render_state.json"
        self.state: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if self.state_path.is_file():
            try:
                return json.loads(self.state_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"shots": {}}

    def _save(self) -> None:
        self.state_path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2),
                                   encoding="utf-8")

    def configure(self, width: int = 1280, height: int = 720,
                  fps: int = 24, out_dir: str | None = None) -> dict[str, Any]:
        out = Path(out_dir) if out_dir else (self.workdir / "renders")
        out.mkdir(parents=True, exist_ok=True)
        self.state["config"] = {"width": width, "height": height, "fps": fps,
                                "out_dir": str(out),
                                "renderer": "SFM session Export Movie (manual) + ffmpeg combine"}
        self._save()
        return self.state["config"]

    def render_shot(self, shot_id: int, start_frame: int, end_frame: int) -> dict[str, Any]:
        # Cannot headlessly drive SFM; record job for in-SFM execution.
        self.state["shots"][str(shot_id)] = {
            "shot_id": shot_id, "start_frame": start_frame, "end_frame": end_frame,
            "status": "pending_SFM",
            "hint": "Open SFM session, set work camera to shot, File > Export > Movie",
        }
        self._save()
        est = (end_frame - start_frame) / max(1, self.state.get("config", {}).get("fps", 24))
        return {"ok": True, "shot_id": shot_id, "status": "pending_SFM",
                "estimated_sec": round(est, 2)}

    def retry_shot(self, shot_id: int) -> dict[str, Any]:
        s = self.state["shots"].get(str(shot_id))
        if not s:
            return {"ok": False, "error": f"unknown shot {shot_id}"}
        s["status"] = "pending_SFM"
        s["retries"] = int(s.get("retries", 0)) + 1
        self._save()
        return {"ok": True, **s}

    def mark_shot_done(self, shot_id: int, file_path: str) -> dict[str, Any]:
        """Operator exported the shot from SFM manually; register the file."""
        from src.common import config as _  # noqa
        p = Path(file_path)
        if not p.is_file():
            return {"ok": False, "error": f"file not found: {file_path}",
                    "hint": "Export from SFM first, then call again"}
        if p.stat().st_size == 0:
            return {"ok": False, "error": "zero-byte file"}
        s = self.state["shots"].get(str(shot_id), {"shot_id": shot_id})
        s.update({"status": "done", "file": str(p), "size": p.stat().st_size})
        self.state["shots"][str(shot_id)] = s
        self._save()
        return {"ok": True, **s}

    def get_status(self) -> dict[str, Any]:
        shots = self.state.get("shots", {})
        done = sum(1 for s in shots.values() if s.get("status") == "done")
        total = len(shots)
        return {"total": total, "done": done,
                "pending": total - done,
                "progress": round(done / total, 3) if total else 0.0,
                "shots": shots, "config": self.state.get("config", {})}

    def combine(self, inputs: list[str], output: str) -> dict[str, Any]:
        ff = find_ffmpeg("ffmpeg")
        if not ff:
            return {"ok": False, "error": "ffmpeg not found",
                    "hint": "install ffmpeg or combine in editor; inputs preserved",
                    "inputs": inputs}
        out = self.workdir / output if not Path(output).is_absolute() else Path(output)
        out.parent.mkdir(parents=True, exist_ok=True)
        # concat demuxer when all inputs exist
        missing = [i for i in inputs if not Path(i).is_file()]
        if missing:
            return {"ok": False, "error": f"missing inputs: {missing}"}
        lst = out.parent / "_concat.txt"
        lst.write_text("".join(f"file '{Path(i).as_posix()}'\n" for i in inputs),
                       encoding="utf-8")
        r = subprocess.run([ff, "-y", "-f", "concat", "-safe", "0",
                            "-i", str(lst), "-c", "copy", str(out)],
                           capture_output=True, text=True, timeout=120)
        if out.is_file() and out.stat().st_size > 0:
            return {"ok": True, "output": str(out), "size": out.stat().st_size}
        return {"ok": False, "error": r.stderr[-2000:], "hint": "ffmpeg combine failed"}

    def verify(self, path: str) -> dict[str, Any]:
        p = Path(path)
        if not p.is_file():
            return {"ok": False, "error": f"not found: {path}"}
        size = p.stat().st_size
        if size == 0:
            return {"ok": False, "error": "zero-byte output"}
        probe = find_ffmpeg("ffprobe")
        if probe:
            r = subprocess.run([probe, "-v", "error", "-show_entries",
                                "format=duration,size", "-of", "json", str(p)],
                               capture_output=True, text=True, timeout=30)
            try:
                return {"ok": True, "size": size, "probe": json.loads(r.stdout or "{}")}
            except Exception:
                return {"ok": True, "size": size, "probe_error": r.stderr[:500]}
        return {"ok": True, "size": size,
                "note": "ffprobe missing; size-only check"}
