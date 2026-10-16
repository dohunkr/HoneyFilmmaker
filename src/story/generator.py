"""Story / storyboard / shot-list generation.

Rule-based fallback works offline without API keys.
Optional LLM adapter interface for provider plug-ins.
"""
from __future__ import annotations
import re
from typing import Any


class LLMAdapter:
    """Interface; implement .generate(prompt)->str in provider plug-ins."""
    name = "none"

    def generate(self, prompt: str) -> str:
        raise NotImplementedError("no LLM configured; set HONEY_LLM_PROVIDER + key, "
                                  "or use rule-based fallback")


def parse_prompt(prompt: str) -> dict[str, Any]:
    p = prompt.lower()
    # duration: "2분", "2 min", "120초"
    seconds = 60
    m = re.search(r"(\d+(?:\.\d+)?)\s*분", prompt)
    if m:
        seconds = int(float(m.group(1)) * 60)
    else:
        m = re.search(r"(\d+(?:\.\d+)?)\s*(min|minute)", p)
        if m:
            seconds = int(float(m.group(1)) * 60)
        else:
            m = re.search(r"(\d+)\s*(초|sec)", prompt.lower())
            if m:
                seconds = int(m.group(1))
    genre = "war"
    if any(k in p for k in ["horror", "공포"]):
        genre = "horror"
    elif any(k in p for k in ["comedy", "개그", "코미디"]):
        genre = "comedy"
    elif any(k in p for k in ["chase", "추격"]):
        genre = "chase"
    twist = any(k in prompt for k in ["반전", "twist", "plot twist"])
    boss = any(k in prompt for k in ["보스", "boss", "거대"])
    return {"seconds": max(10, min(seconds, 1200)), "genre": genre,
            "twist": twist, "boss": boss, "raw": prompt}


def generate_story(prompt: str, llm: LLMAdapter | None = None) -> dict[str, Any]:
    if llm is not None:
        try:
            text = llm.generate(f"Create a short 3D animation story for: {prompt}")
            return {"mode": f"llm:{llm.name}", "story": text,
                    "spec": parse_prompt(prompt)}
        except NotImplementedError:
            pass
        except Exception as e:  # noqa: BLE001
            return {"mode": "llm_error", "error": str(e),
                    "fallback": _rule_story(parse_prompt(prompt))}
    return _rule_story(parse_prompt(prompt))


def _rule_story(spec: dict[str, Any]) -> dict[str, Any]:
    secs = spec["seconds"]
    n_scenes = max(2, min(8, secs // 20))
    chars = ["카메라맨 리더", "카메라맨 스카우트", "토일렛 그런트 x3"]
    if spec["boss"]:
        chars.append("거대 토일렛 보스")
    beats = ["도입: 도시 전경, 양 진영 등장", "전투 발발: 거리전, 폭발",
             "중반 위기: 아군 후퇴" + (", 보스 등장" if spec["boss"] else ""),
             "반격: 협공 작전"]
    ending = "반전: 쓰러진 보스의 눈이 다시 켜지며 속편 암시" if spec["twist"] \
        else "결말: 도시 탈환, 전우를 기리며 마무리"
    beats.append(ending)
    return {"mode": "rule_based", "spec": spec,
            "title": "무제 전쟁 애니메이션",
            "genre": spec["genre"], "duration_sec": secs,
            "characters": chars, "beats": beats,
            "dialogue_hints": ["전진!", "폭탄이다, 엎드려!", "지금이다, 쏴라!"]}


def generate_storyboard(story: dict[str, Any], fps: int = 24) -> dict[str, Any]:
    secs = int(story.get("duration_sec") or story.get("spec", {}).get("seconds", 60))
    beats: list[str] = story.get("beats", ["도입", "전개", "결말"])
    n = len(beats)
    per = secs / max(1, n)
    scenes = []
    t = 0.0
    for i, b in enumerate(beats):
        scenes.append({"scene_id": i + 1, "beat": b,
                       "start_sec": round(t, 2), "end_sec": round(t + per, 2),
                       "frames": int(per * fps)})
        t += per
    return {"fps": fps, "total_sec": secs, "total_frames": secs * fps, "scenes": scenes}


SHOT_TYPES = ["wide", "medium", "closeup", "tracking", "overhead", "low_angle"]


def create_shot_list(storyboard: dict[str, Any]) -> dict[str, Any]:
    shots: list[dict[str, Any]] = []
    sid = 0
    for sc in storyboard.get("scenes", []):
        dur = sc["end_sec"] - sc["start_sec"]
        # 2-3 shots per scene, rotate types for diversity
        n_shots = 3 if dur >= 15 else 2
        for k in range(n_shots):
            sid += 1
            st = SHOT_TYPES[(sid + sc["scene_id"]) % len(SHOT_TYPES)]
            s = dur / n_shots
            shots.append({"shot_id": sid, "scene_id": sc["scene_id"],
                          "shot_type": st,
                          "start_sec": round(sc["start_sec"] + k * s, 2),
                          "end_sec": round(sc["start_sec"] + (k + 1) * s, 2),
                          "camera_hint": f"{st} shot",
                          "action_hint": sc.get("beat", "")})
    return {"shot_count": len(shots), "shots": shots,
            "estimated_frames": storyboard.get("total_frames", 0)}
