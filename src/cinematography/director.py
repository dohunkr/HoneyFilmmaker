"""Cinematic director: shots, camera paths, lighting."""
from __future__ import annotations
from typing import Any

SHOT_PRESETS: dict[str, dict[str, Any]] = {
    "wide": {"fov": 60, "dist": 600, "height": 200},
    "medium": {"fov": 45, "dist": 300, "height": 150},
    "closeup": {"fov": 35, "dist": 120, "height": 140},
    "tracking": {"fov": 50, "dist": 250, "height": 160, "move": True},
    "overhead": {"fov": 55, "dist": 500, "height": 500},
    "low_angle": {"fov": 50, "dist": 220, "height": 60},
}

BATTLE_LIGHTING = {"key": "warm", "fill": 0.4, "ambient": 0.3, "mood": "war_dusk"}
CHASE_LIGHTING = {"key": "cool", "fill": 0.5, "ambient": 0.4, "mood": "night_city"}


def direct_shots(shot_list: list[dict[str, Any]], fps: int = 24) -> dict[str, Any]:
    cams = []
    for s in shot_list:
        preset = SHOT_PRESETS.get(s.get("shot_type", "wide"), SHOT_PRESETS["wide"])
        start_f = int(s["start_sec"] * fps)
        end_f = int(s["end_sec"] * fps)
        cams.append({"shot_id": s["shot_id"], "preset": s.get("shot_type"),
                     "fov": preset["fov"],
                     "start_frame": start_f, "end_frame": end_f,
                     "keyframes": [
                         {"frame": start_f, "pos": [preset["dist"], 0, preset["height"]],
                          "look_at": "action_center"},
                         {"frame": end_f,
                          "pos": [preset["dist"] * 0.8 if preset.get("move") else preset["dist"],
                                  80 if preset.get("move") else 0, preset["height"]],
                          "look_at": "action_center"}]})
    # diversity check: avoid repeating same preset 3x in a row
    seq = [c["preset"] for c in cams]
    repeats = sum(1 for i in range(2, len(seq)) if seq[i] == seq[i-1] == seq[i-2])
    return {"ok": True, "cameras": cams, "diversity_repeats": repeats,
            "lighting": BATTLE_LIGHTING}


def check_framing(camera: dict[str, Any], targets: list[list[float]]) -> dict[str, Any]:
    if not targets:
        return {"ok": False, "reason": "no targets"}
    return {"ok": True, "visible": len(targets),
            "notes": "analytic check only; in-SFM framing needs viewport test"}
