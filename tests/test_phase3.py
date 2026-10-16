"""Phase3/4 tests: combat/chase, synth audio, auto-fix, run_auto, resume."""
import tempfile
import unittest
from pathlib import Path


def _tmp():
    return Path(tempfile.mkdtemp(prefix="honey34"))


class TestCombat(unittest.TestCase):
    def test_combat_chain(self):
        from src.animation import engine as e
        r = e.compose_combat("A", "V", 0.0)
        self.assertTrue(r["ok"])
        self.assertEqual(r["beats"], ["attack", "hit", "fall"])

    def test_chase_gap(self):
        from src.animation import engine as e
        r = e.compose_chase("C", "R", 0.0, 2.0)
        self.assertTrue(r["ok"])
        self.assertTrue(r["gap_maintained"])

    def test_retarget_gate(self):
        from src.animation import engine as e
        ok = e.retarget_report(["root", "spine", "head"], "x.mdl")
        self.assertTrue(ok["ok"])
        bad = e.retarget_report(["root"], "x.mdl")
        self.assertFalse(bad["ok"])


class TestSynthAudio(unittest.TestCase):
    def test_silent_and_sfx_validate(self):
        from src.audio import director as a
        d = Path(_tmp())
        p1 = d / "s.wav"
        a.synth_silent_wav(p1, 0.5)
        v = a.validate_wav(str(p1))
        self.assertTrue(v["ok"])
        self.assertAlmostEqual(v["seconds"], 0.5, places=1)
        p2 = d / "boom.wav"
        a.synth_sfx_wav(p2, "explosion", 0.5)
        self.assertTrue(a.validate_wav(str(p2))["ok"])

    def test_place_synthesize(self):
        from src.audio import director as a
        w = _tmp()
        r = a.place_cues([{"scene_id": 1, "start_sec": 0}], [{"shot_id": 1, "start_sec": 0}],
                         w, synthesize=True)
        self.assertTrue(r["ok"])
        self.assertIn("placeholder", r["cues"][0]["status"])


class TestAutoFlow(unittest.TestCase):
    def test_run_auto_short(self):
        from src.orchestrator.orchestrator import Orchestrator
        o = Orchestrator(_tmp())
        r = o.run_auto("30초 추격, 반전 포함", fps=24)
        self.assertTrue(r["ok"])
        self.assertGreater(len(r["steps"]), 5)
        self.assertIn("preview", r["project"])
        # resume works from saved json
        rr = o.resume(r["project_id"])
        self.assertTrue(rr["ok"])

    def test_apply_fixes(self):
        import json
        from src.orchestrator.orchestrator import Orchestrator
        w = _tmp()
        o = Orchestrator(w)
        (w / "scene.json").write_text(json.dumps(
            {"objects": {"a": {"pos": [0, 0, -5]}, "b": {"pos": [1, 0, 0]}}}),
            encoding="utf-8")
        out = o.apply_fixes()
        self.assertTrue(out["ok"])
        self.assertGreaterEqual(out["fixed"], 1)

    def test_mark_done_and_combine_honest(self):
        from src.rendering.manager import find_ffmpeg
        self.assertIsNotNone(find_ffmpeg("ffmpeg"))
        self.assertIsNotNone(find_ffmpeg("ffprobe"))

    def test_new_tools_registered(self):
        from src.server.mcp_server import build_registry
        reg = build_registry(_tmp())
        names = {t["name"] for t in reg.spec_list()}
        for n in ["run_full_auto", "resume_project", "apply_auto_fixes",
                  "mark_shot_done", "compose_combat", "compose_chase",
                  "synth_audio_placeholders", "validate_wav", "combine_shots"]:
            self.assertIn(n, names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
