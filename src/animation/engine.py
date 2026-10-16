"""Animation engine: keyframes, clips, blending, spatial checks."""
from __future__ import annotations
import math
from typing import Any

ACTIONS = {"idle", "walk", "run", "chase", "attack", "hit", "jump", "fall",
           "explode", "appear", "boss_entrance"}


class MotionAdapter:
    """External AI motion model plug-in point."""
    name = "none"

    def generate(self, action: str, seconds: float, fps: int) -> list[dict[str, Any]]:
        raise NotImplementedError("no external motion model connected; "
                                   "use built-in keyframes/clips")


MOTION_REGISTRY: dict[str, MotionAdapter] = {}


def register_motion(adapter: MotionAdapter) -> None:
    MOTION_REGISTRY[adapter.name] = adapter


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def generate_keyframes(obj: str, action: str, start_sec: float,
                       end_sec: float, fps: int = 24,
                       frm: list[float] | None = None,
                       to: list[float] | None = None) -> dict[str, Any]:
    if action not in ACTIONS:
        return {"ok": False, "error": f"unknown action {action}",
                "hint": f"allowed: {sorted(ACTIONS)}"}
    frm = frm or [0, 0, 0]
    to = to or [100, 0, 0]
    n = max(2, int((end_sec - start_sec) * fps) + 1)
    keys = []
    hop = 30.0 if action in ("jump", "fall") else 0.0
    for i in range(n):
        t = i / (n - 1)
        pos = [lerp(frm[j], to[j], t) for j in range(3)]
        if hop:
            pos[2 if len(pos) > 2 else 1] += math.sin(t * math.pi) * hop
        keys.append({"t": round(start_sec + t * (end_sec - start_sec), 3),
                     "pos": [round(v, 2) for v in pos],
                     "rot": [0, 90 * t if action in ("run", "chase") else 0, 0]})
    return {"ok": True, "object": obj, "action": action, "fps": fps,
            "keyframes": keys}


def blend(motions: list[dict[str, Any]]) -> dict[str, Any]:
    out: list[dict[str, Any]] = []
    for m in motions:
        out.extend(m.get("keyframes", []))
    out.sort(key=lambda k: k["t"])
    return {"ok": True, "keyframes": out, "count": len(out)}


def check_space(objects: dict[str, list[float]], min_dist: float = 40.0) -> dict[str, Any]:
    names = list(objects.keys())
    collisions = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = objects[names[i]], objects[names[j]]
            d = math.dist(a[:3], b[:3])
            if d < min_dist:
                collisions.append({"a": names[i], "b": names[j], "dist": round(d, 1)})
    under = [n for n, p in objects.items() if len(p) >= 3 and p[2] < 0]
    floating = [n for n, p in objects.items() if len(p) >= 3 and p[2] > 300]
    return {"ok": len(collisions) == 0 and not under,
            "collisions": collisions, "below_ground": under, "floating": floating}


def validate_rig(asset_path: str, wanted_bones: list[str] | None = None) -> dict[str, Any]:
    # Without parsing .mdl binary fully, do an honest filename-level check.
    p = asset_path.lower()
    if not p.endswith(".mdl"):
        return {"ok": False, "compatible": False, "reason": "not a .mdl"}
    return {"ok": True, "compatible": None,
            "notes": "rig bone check needs SFM session or mdl parser; "
                     "wanted_bones=" + str(wanted_bones or ["root", "spine"]),
            "hint": "open model in SFM Model Viewer to confirm bones"}


def compose_combat(attacker: str, victim: str, start_sec: float,
                   fps: int = 24) -> dict[str, Any]:
    """Attack -> hit -> fall chain with spatial offsets. Analytic, SFM-agnostic."""
    a1 = generate_keyframes(attacker, "attack", start_sec, start_sec + 0.8,
                            fps=fps, frm=[0, 0, 0], to=[60, 0, 0])
    h1 = generate_keyframes(victim, "hit", start_sec + 0.6, start_sec + 1.2,
                            fps=fps, frm=[120, 0, 0], to=[150, 0, 0])
    f1 = generate_keyframes(victim, "fall", start_sec + 1.2, start_sec + 2.0,
                            fps=fps, frm=[150, 0, 0], to=[170, 0, 0])
    if not (a1.get("ok") and h1.get("ok") and f1.get("ok")):
        return {"ok": False, "error": "keyframe gen failed"}
    bl = blend([a1, h1, f1])
    return {"ok": True, "attacker": attacker, "victim": victim,
            "keyframes": bl["keyframes"], "count": bl["count"],
            "beats": ["attack", "hit", "fall"]}


def compose_chase(chaser: str, runner: str, start_sec: float,
                  end_sec: float, fps: int = 24) -> dict[str, Any]:
    c = generate_keyframes(chaser, "chase", start_sec, end_sec, fps=fps,
                           frm=[-100, 0, 0], to=[200, 30, 0])
    r = generate_keyframes(runner, "run", start_sec, end_sec, fps=fps,
                           frm=[-40, 0, 0], to=[260, 30, 0])
    if not (c.get("ok") and r.get("ok")):
        return {"ok": False, "error": "keyframe gen failed"}
    # runner stays ahead: verify min gap
    gap_ok = True
    for kc, kr in zip(c["keyframes"], r["keyframes"]):
        dx = kr["pos"][0] - kc["pos"][0]
        if dx < 20:
            gap_ok = False
            break
    bl = blend([c, r])
    return {"ok": True, "gap_maintained": gap_ok, "keyframes": bl["keyframes"],
            "count": bl["count"]}


def retarget_report(src_bones: list[str], dst_asset: str) -> dict[str, Any]:
    base = ["root", "spine", "head"]
    missing = [b for b in base if b not in (src_bones or [])]
    return {"ok": len(missing) == 0, "dst": dst_asset,
            "missing_base_bones": missing,
            "note": "full retarget needs bone-map + scale; this is a base-bone gate"}


def find_motion_clips(game_dir: str, action: str, limit: int = 20) -> dict[str, Any]:
    """Search for reusable motion sources (.dmx/.smd) offline."""
    from pathlib import Path as _P
    gd = _P(game_dir)
    if not gd.is_dir():
        return {"ok": False, "error": "game dir missing"}
    hits: list[str] = []
    for ext in ("*.dmx", "*.smd"):
        try:
            for p in gd.rglob(ext):
                if action.lower() in p.name.lower() or "anim" in p.name.lower():
                    hits.append(str(p.relative_to(gd)))
                    if len(hits) >= limit:
                        break
        except OSError:
            continue
    return {"ok": True, "action": action, "clips": hits,
            "note": "built-in keyframes remain primary; clips are candidates"}
