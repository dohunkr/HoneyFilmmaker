"""Animation/camera/audio/QA tests."""
import tempfile
import unittest
from pathlib import Path


def _tmp():
    return Path(tempfile.mkdtemp(prefix="honey2"))


class TestMotion(unittest.TestCase):
    def test_keyframes_and_blend(self):
        from src.animation import engine as e
        a = e.generate_keyframes("hero", "run", 0, 2, fps=24)
        self.assertTrue(a["ok"])
        self.assertGreater(len(a["keyframes"]), 10)
        b = e.generate_keyframes("hero", "jump", 2, 3, fps=24)
        bl = e.blend([a, b])
        self.assertGreater(bl["count"], len(a["keyframes"]))
        bad = e.generate_keyframes("hero", "fly_to_moon", 0, 1)
        self.assertFalse(bad["ok"])

    def test_space_and_rig(self):
        from src.animation import engine as e
        r = e.check_space({"a": [0, 0, 0], "b": [10, 0, 0]}, min_dist=40)
        self.assertFalse(r["ok"])
        self.assertEqual(len(r["collisions"]), 1)
        g = e.check_space({"a": [0, 0, -5]})
        self.assertIn("a", g["below_ground"])
        rig = e.validate_rig("models/x.mdl")
        self.assertTrue(rig["ok"])


class TestCineAudio(unittest.TestCase):
    def test_direct_diversity(self):
        from src.cinematography import director as c
        shots = [{"shot_id": i + 1, "shot_type": ["wide", "medium", "closeup"][i % 3],
                  "start_sec": i * 5, "end_sec": i * 5 + 5} for i in range(6)]
        d = c.direct_shots(shots)
        self.assertTrue(d["ok"])
        self.assertEqual(len(d["cameras"]), 6)

    def test_dialogue_cues_missing_honest(self):
        from src.audio import director as a
        d = a.generate_dialogue([{"scene_id": 1, "start_sec": 0}])
        self.assertTrue(d["ok"])
        cues = a.place_cues(d["lines"], [], _tmp())
        self.assertIn("missing", cues["cues"][0]["status"])
        v = a.validate_wav(str(_tmp() / "no.wav"))
        self.assertFalse(v["ok"])


class TestQA(unittest.TestCase):
    def test_review_and_plan(self):
        from src.quality import qa as q
        r = q.review_scene({"a": [0, 0, -1]}, [], render_path="no.mp4")
        self.assertFalse(r["ok"])
        p = q.plan_fixes(r)
        self.assertGreater(len(p["auto_fixable"]) + len(p["needs_manual"]), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
