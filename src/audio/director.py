"""Audio director: dialogue drafts + cue sheet + wav validation."""
from __future__ import annotations
import wave
from pathlib import Path
from typing import Any


class TTSAdapter:
    name = "none"

    def synth(self, text: str, voice: str, out_path: Path) -> Path:
        raise NotImplementedError("no TTS engine configured; "
                                  "install one (e.g. Piper/Coqui/offline) and implement TTSAdapter")


TTS_REGISTRY: dict[str, TTSAdapter] = {}


def register_tts(adapter: TTSAdapter) -> None:
    TTS_REGISTRY[adapter.name] = adapter


def synth_silent_wav(out_path: Path, seconds: float, rate: int = 22050) -> Path:
    """Offline placeholder so timeline/verify can run. Honestly labeled silent."""
    import struct
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = max(1, int(seconds * rate))
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<%dh" % n, *[0] * n))
    return out_path


def synth_sfx_wav(out_path: Path, kind: str = "explosion",
                  seconds: float = 1.0, rate: int = 22050) -> Path:
    """Synthesized (not sampled) SFX via stdlib only. Labeled synthesized."""
    import math
    import random
    import struct
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = max(1, int(seconds * rate))
    frames: list[int] = []
    for i in range(n):
        t = i / rate
        env = max(0.0, 1.0 - i / n)
        if kind == "explosion":
            v = (random.random() * 2 - 1) * env * env
        elif kind == "gunshot":
            v = (random.random() * 2 - 1) * env if i < n // 8 else 0.0
        elif kind == "rain":
            # soft loopable noise bed (no decay): lowpassed random
            v = (random.random() * 2 - 1) * 0.18
        elif kind == "wind":
            # slow swell: noise * low-freq LFO
            v = (random.random() * 2 - 1) * 0.25 * (0.5 + 0.5 * math.sin(2 * math.pi * 0.2 * t))
        elif kind == "sword":
            # metallic clash: detuned high sines, fast decay
            v = (math.sin(2 * math.pi * 1567 * t) + math.sin(2 * math.pi * 2093 * t)) * 0.3 * env * env
        else:  # beep / whoosh fallback
            v = math.sin(2 * math.pi * 440 * t) * 0.4 * env
        frames.append(int(max(-1.0, min(1.0, v)) * 32767))
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<%dh" % n, *frames))
    return out_path


def generate_dialogue(scenes: list[dict[str, Any]]) -> dict[str, Any]:
    lines = []
    bank = ["전진! 대열 유지해!", "폭탄이다, 엎드려!", "보스다! 화력 집중!",
            "지금이다, 쏴라!", "버텨! 지원 온다!"]
    for i, sc in enumerate(scenes):
        lines.append({"scene_id": sc.get("scene_id", i + 1),
                      "speaker": "리더" if i % 2 == 0 else "스카우트",
                      "text": bank[i % len(bank)],
                      "start_sec": sc.get("start_sec", 0)})
    return {"ok": True, "lines": lines}


def place_cues(dialogue: list[dict[str, Any]], shots: list[dict[str, Any]],
               workdir: Path, synthesize: bool = False) -> dict[str, Any]:
    cue_dir = workdir / "audio_cues"
    cue_dir.mkdir(parents=True, exist_ok=True)
    cues = []
    for d in dialogue:
        wav = cue_dir / f"scene{d.get('scene_id')}.wav"
        status = "missing_tts"
        if synthesize:
            dur = 2.0
            synth_silent_wav(wav, dur)
            status = "placeholder_silent (no TTS voice; timeline only)"
        cues.append({**d, "wav_expected": str(wav), "status": status})
    # battle sfx placeholders
    for s in shots[:4]:
        wav = cue_dir / f"sfx_explosion_{s.get('shot_id')}.wav"
        status = "missing_file"
        if synthesize:
            synth_sfx_wav(wav, "explosion", 1.0)
            status = "synthesized (not sampled)"
        cues.append({"kind": "sfx", "name": "explosion",
                     "at_sec": s.get("start_sec"), "wav_expected": str(wav),
                     "status": status})
    return {"ok": True, "cue_dir": str(cue_dir), "cues": cues,
            "note": "TTS voices need engine; silent/synth placeholders used when synthesize=true"}


def validate_wav(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        return {"ok": False, "error": f"missing: {path}"}
    try:
        with wave.open(str(p), "rb") as w:
            return {"ok": True, "channels": w.getnchannels(),
                    "framerate": w.getframerate(),
                    "frames": w.getnframes(),
                    "seconds": round(w.getnframes() / w.getframerate(), 2)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"not a valid wav: {e}"}
