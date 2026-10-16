"""Phase1-2 tests: stdlib unittest, no SFM/network/keys required."""
import json
import tempfile
import unittest
from pathlib import Path


def _tmp():
    return Path(tempfile.mkdtemp(prefix="honey test " .strip()))


class TestServerBoot(unittest.TestCase):
    def test_registry_lists_all_tools(self):
        from src.server.mcp_server import build_registry
        reg = build_registry(_tmp())
        names = {t["name"] for t in reg.spec_list()}
        for need in ["sfm_get_status", "sfm_connect", "sfm_get_session_info",
                     "create_animation_project", "get_project_status",
                     "generate_story_and_script", "generate_storyboard",
                     "create_shot_list", "plan_animation_sequence",
                     "search_assets", "inspect_asset", "find_compatible_motion",
                     "prepare_scene_assets", "create_scene", "add_model",
                     "set_object_transform", "list_scene_objects", "configure_lighting",
                     "generate_character_motion", "apply_motion_clip",
                     "set_animation_keyframe", "assemble_animation_sequence",
                     "validate_character_motion", "create_camera",
                     "direct_cinematic_shots", "generate_dialogue_and_audio",
                     "place_audio_cues", "preview_scene", "render_animation",
                     "get_render_status", "review_animation", "fix_animation_issues",
                     "get_final_output"]:
            self.assertIn(need, names, f"missing tool {need}")

    def test_tool_schema_present(self):
        from src.server.mcp_server import build_registry
        reg = build_registry(_tmp())
        for t in reg.spec_list():
            self.assertIn("name", t)
            self.assertIn("inputSchema", t)

    def test_stdio_envelope(self):
        from src.server.mcp_server import build_registry, handle_message
        reg = build_registry(_tmp())
        r = handle_message(reg, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertIn("result", r)
        r2 = handle_message(reg, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                  "params": {"name": "sfm_get_status", "arguments": {}}})
        self.assertIn("result", r2)
        payload = json.loads(r2["result"]["content"][0]["text"])
        self.assertIn("ok", payload)


class TestSFMDetection(unittest.TestCase):
    def test_status_honest_when_down(self):
        from src.server.mcp_server import build_registry
        reg = build_registry(_tmp())
        out = reg.call("sfm_get_status", {})
        self.assertTrue(out["ok"])
        # must report booleans, never claim connected blindly
        self.assertIn("sfm_running", out["data"])
        self.assertIn("connected", out["data"])

    def test_no_fake_success_without_connection(self):
        from src.server.mcp_server import build_registry
        from src.bridge.sfm_bridge import is_sfm_running
        running, _ = is_sfm_running()
        reg = build_registry(_tmp())
        out = reg.call("create_scene", {"name": "t"})
        # analytic scene is ok, but queued SFM cmd must be honest
        q = out["data"]["sfm_queue"]
        if not running:
            self.assertFalse(q["ok"])

    def test_connect_reports_fix(self):
        from src.server.mcp_server import build_registry
        reg = build_registry(_tmp())
        out = reg.call("sfm_connect", {})
        # either connected or honest error with hint
        if not out.get("ok"):
            self.assertIn("hint", out.get("error", {}))


class TestAssetsScenes(unittest.TestCase):
    def test_scan_and_search(self):
        from src.server.mcp_server import build_registry
        reg = build_registry(_tmp())
        out = reg.call("prepare_scene_assets", {})
        self.assertTrue(out["ok"])
        s = reg.call("search_assets", {"query": "2fort", "kind": "maps"})
        self.assertTrue(s["ok"])

    def test_inspect_blocks_escape(self):
        from src.assets.manager import AssetManager
        am = AssetManager(_tmp())
        am.game_dir = am.workdir  # sandbox
        r = am.inspect("../../evil.mdl")
        self.assertFalse(r.get("ok"))

    def test_scene_plan_order(self):
        from src.server.mcp_server import build_registry
        reg = build_registry(_tmp())
        story = reg.call("generate_story_and_script",
                         {"prompt": "스키비디 토일렛 스타일 2분 전쟁, 보스와 반전"})
        self.assertTrue(story["ok"])
        board = reg.call("generate_storyboard", {"story": story["data"]})
        shots = reg.call("create_shot_list", {"storyboard": board["data"]})
        self.assertGreater(shots["data"]["shot_count"], 0)
        # shot times ordered
        ss = shots["data"]["shots"]
        for a, b in zip(ss, ss[1:]):
            self.assertLessEqual(a["start_sec"], b["start_sec"])


class TestQueueRecovery(unittest.TestCase):
    def test_retry_and_resume(self):
        from src.common.job_queue import JobQueue
        q = JobQueue(_tmp() / "q.json", max_retries=2)
        calls = {"n": 0}

        def flaky(payload, prog):
            calls["n"] += 1
            prog(0.5)
            if calls["n"] < 2:
                raise RuntimeError("boom")
            return {"done": True}

        q.register("flaky", flaky)
        j = q.submit("flaky", {})
        r = q.run_sync(j.id)
        self.assertEqual(r.status, "done")
        # persistence across restart
        q2 = JobQueue(q.persist_path)
        self.assertIn(j.id, q2.jobs)


class TestRenderVerify(unittest.TestCase):
    def test_missing_file_honest(self):
        from src.server.mcp_server import build_registry
        reg = build_registry(_tmp())
        out = reg.call("get_final_output", {"path": str(_tmp() / "nope.mp4")})
        self.assertTrue(out["ok"])
        self.assertFalse(out["data"]["ok"])

    def test_full_prompt_to_plan(self):
        from src.server.mcp_server import build_registry
        reg = build_registry(_tmp())
        out = reg.call("plan_animation_sequence",
                       {"prompt": "카메라맨 군대와 토일렛 군단 도시 전투, 보스, 반전 2분"})
        self.assertTrue(out["ok"])
        self.assertGreater(out["data"]["total_frames"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
