"""Asset Manager: index + search + compatibility. Offline-capable."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from src.common import config as cfg


MODEL_EXTS = {".mdl"}
AUDIO_EXTS = {".wav", ".mp3"}
PARTICLE_EXTS = {".pcf"}
MAP_EXTS = {".bsp", ".vmf"}
MATERIAL_EXTS = {".vmt", ".vtf"}


class AssetManager:
    def __init__(self, workdir: Path | None = None, game_dir: Path | None = None) -> None:
        self.workdir = cfg.resolve_workdir(str(workdir) if workdir else None)
        self.game_dir = game_dir or cfg.find_game_dir()
        self.index_path = self.workdir / "asset_index.json"
        self.index: dict[str, Any] = {"models": [], "maps": [], "sounds": [],
                                      "particles": [], "materials": []}

    def scan(self, limit_per_kind: int = 2000, force: bool = False) -> dict[str, Any]:
        # Reuse fresh cache to avoid rescanning 100k+ SFM files on every call.
        if not force and self.index_path.is_file():
            try:
                import time
                if time.time() - self.index_path.stat().st_mtime < 3600:
                    cached = json.loads(self.index_path.read_text(encoding="utf-8"))
                    if int(cached.get("count", 0)) > 0:
                        self.index = cached
                        return self.index
            except Exception:
                pass
        idx: dict[str, list[dict[str, Any]]] = {"models": [], "maps": [],
                                                "sounds": [], "particles": [], "materials": []}
        missing_game_dir = self.game_dir is None or not Path(str(self.game_dir)).is_dir()
        if missing_game_dir:
            self.index = {**idx, "game_dir": None, "count": 0,
                          "warning": "SFM game dir not found; index empty"}
            self._save()
            return self.index
        gd = Path(str(self.game_dir))
        # Single-pass walk (was 5x rglob -> ~100s). Stop when all kinds hit limit.
        import os
        roots = [gd / "tf", gd / "hl2", gd / "platform"]
        roots = [r for r in roots if r.is_dir()] or [gd]
        ext_to_key = {}
        for exts, key in [(MODEL_EXTS, "models"), (MAP_EXTS, "maps"),
                          (AUDIO_EXTS, "sounds"), (PARTICLE_EXTS, "particles"),
                          (MATERIAL_EXTS, "materials")]:
            for e in exts:
                ext_to_key[e] = key
        for root in roots:
            done = all(len(idx[k]) >= limit_per_kind for k in idx)
            if done:
                break
            for dirpath, _dirnames, filenames in os.walk(root):
                for fn in filenames:
                    dot = fn.rfind(".")
                    suf = fn[dot:].lower() if dot >= 0 else ""
                    key = ext_to_key.get(suf)
                    if key is None or len(idx[key]) >= limit_per_kind:
                        continue
                    try:
                        full = Path(dirpath) / fn
                        rel = str(full.relative_to(gd))
                        idx[key].append({"path": rel, "abs": str(full),
                                         "size": full.stat().st_size})
                    except OSError:
                        continue
                if all(len(idx[k]) >= limit_per_kind for k in idx):
                    break
        self.index = {**idx, "game_dir": str(gd),
                      "count": sum(len(v) for v in idx.values())}
        self._save()
        return self.index

    def _save(self) -> None:
        self.index_path.write_text(json.dumps(self.index, ensure_ascii=False, indent=2)[:2_000_000],
                                   encoding="utf-8")

    def load(self) -> dict[str, Any]:
        if self.index_path.is_file():
            try:
                self.index = json.loads(self.index_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return self.index

    def search(self, query: str, kind: str = "models", limit: int = 20) -> dict[str, Any]:
        data = self.load()
        items = data.get(kind, [])
        q = query.lower()
        scored = []
        for it in items:
            hay = str(it.get("path", "")).lower()
            if q in hay:
                # prefer shorter / character-like paths
                scored.append((len(hay), it))
        scored.sort(key=lambda t: t[0])
        results = [it for _, it in scored[:limit]]
        return {"query": query, "kind": kind, "count": len(results),
                "total_indexed": len(items), "results": results}

    def inspect(self, asset_path: str) -> dict[str, Any]:
        gd = Path(str(self.game_dir)) if self.game_dir else None
        # path safety: only allow relative paths inside game dir
        if gd is None:
            return {"ok": False, "error": "game dir unknown"}
        # block absolute escapes
        p = (gd / asset_path)
        try:
            rp = p.resolve()
            if gd.resolve() not in rp.parents and rp != gd.resolve():
                return {"ok": False, "error": f"path escapes game dir: {asset_path}"}
            if not rp.is_file():
                return {"ok": False, "error": f"asset not found: {asset_path}",
                        "hint": "run scan then search_assets"}
            return {"ok": True, "path": asset_path, "size": rp.stat().st_size,
                    "suffix": rp.suffix.lower(),
                    "exists": True}
        except OSError as e:
            return {"ok": False, "error": str(e)}

    def check_compat(self, asset_path: str) -> dict[str, Any]:
        suf = Path(asset_path).suffix.lower()
        if suf == ".mdl":
            return {"ok": True, "compatible": True, "notes": "mdl loadable via SFM model entity"}
        if suf in (".bsp", ".vmf"):
            return {"ok": True, "compatible": True, "notes": "map usable as SFM session map"}
        if suf in (".wav", ".mp3"):
            conv = suf == ".mp3"
            return {"ok": True, "compatible": True,
                    "notes": "mp3 should be converted to wav for SFM" if conv else "wav ok"}
        return {"ok": True, "compatible": None,
                "notes": f"unverified suffix {suf}; manual check needed"}

    def missing_report(self, wanted: list[str]) -> dict[str, Any]:
        missing, found = [], []
        for w in wanted:
            r = self.inspect(w)
            (found if r.get("ok") else missing).append(w)
        return {"found": found, "missing": missing,
                "suggestion": "Provide workshop/GCFS path or place file under game dir; "
                              "record license/source before importing" if missing else ""}
