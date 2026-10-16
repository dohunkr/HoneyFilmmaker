"""QA agent: scene + render checks, fix planner."""
from __future__ import annotations
from pathlib import Path
from typing import Any


def review_scene(objects: dict[str, list[float]], cameras: list[dict],
                render_path: str | None = None,
                duration_sec: float | None = None) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    for name, pos in objects.items():
        if len(pos) >= 3 and pos[2] < 0:
            issues.append({"type": "below_ground", "object": name, "pos": pos})
        if len(pos) >= 3 and pos[2] > 300:
            issues.append({"type": "floating", "object": name, "pos": pos})
    names = list(objects.keys())
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = objects[names[i]], objects[names[j]]
            try:
                import math
                if math.dist(a[:3], b[:3]) < 5:
                    issues.append({"type": "overlap", "a": names[i], "b": names[j]})
            except Exception:
                pass
    if not cameras:
        issues.append({"type": "no_camera", "message": "no cameras directed"})
    if render_path:
        p = Path(render_path)
        if not p.is_file():
            issues.append({"type": "missing_output", "path": render_path})
        elif p.stat().st_size == 0:
            issues.append({"type": "zero_output", "path": render_path})
    if duration_sec is not None and duration_sec < 5:
        issues.append({"type": "too_short", "duration": duration_sec})
    return {"ok": len(issues) == 0, "issue_count": len(issues), "issues": issues}


def plan_fixes(review: dict[str, Any]) -> dict[str, Any]:
    steps = []
    for it in review.get("issues", []):
        t = it.get("type")
        if t == "below_ground":
            steps.append({"fix": "lift_to_ground", "object": it.get("object"),
                          "action": "set z >= 0"})
        elif t == "floating":
            steps.append({"fix": "lower", "object": it.get("object")})
        elif t == "overlap":
            steps.append({"fix": "separate", "a": it.get("a"), "b": it.get("b"),
                          "action": "move apart >= 40 units"})
        elif t == "no_camera":
            steps.append({"fix": "direct_cinematic_shots"})
        elif t in ("missing_output", "zero_output"):
            steps.append({"fix": "re_render", "path": it.get("path")})
        elif t == "too_short":
            steps.append({"fix": "extend_timeline"})
        else:
            steps.append({"fix": "manual_review", "issue": it})
    auto = [s for s in steps if s["fix"] in ("lift_to_ground", "lower", "separate")]
    manual = [s for s in steps if s not in auto]
    return {"ok": True, "auto_fixable": auto, "needs_manual": manual}
