"""Tool registry: schemas + handlers. Stdlib only."""
from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Any

from src.common import config as cfg
from src.common.validation import validate_schema, ok_result, err_result
from src.common.logging_utils import append_jsonl, Timer
from src.bridge.sfm_bridge import SFMBridge
from src.orchestrator.orchestrator import Orchestrator
from src.story import generator as story_gen
from src.assets.manager import AssetManager
from src.animation import engine as anim
from src.cinematography import director as cine
from src.audio import director as audio_dir
from src.rendering.manager import RenderManager
from src.quality import qa as qa_mod


def _scene_path(workdir: Path) -> Path:
    return workdir / "scene.json"


def _load_scene(workdir: Path) -> dict[str, Any]:
    p = _scene_path(workdir)
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"objects": {}, "cameras": {}, "lights": {}, "keyframes": []}


def _save_scene(workdir: Path, scene: dict[str, Any]) -> None:
    _scene_path(workdir).write_text(json.dumps(scene, ensure_ascii=False, indent=2),
                                    encoding="utf-8")


class ToolRegistry:
    def __init__(self, workdir: Path | None = None) -> None:
        self.workdir = cfg.resolve_workdir(str(workdir) if workdir else None)
        self.bridge = SFMBridge(self.workdir)
        self.orch = Orchestrator(self.workdir)
        self.assets = AssetManager(self.workdir)
        self.renderer = RenderManager(self.workdir)
        self.log_path = self.workdir / "tool_calls.jsonl"
        self.tools: dict[str, dict[str, Any]] = {}
        self._register_all()

    def _add(self, name: str, desc: str, schema: dict, fn) -> None:
        self.tools[name] = {"description": desc, "input_schema": schema, "handler": fn}

    def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        t = time.perf_counter()
        tool = self.tools.get(name)
        if tool is None:
            return err_result(name, f"unknown tool: {name}", hint="use tools/list")
        ok, msg = validate_schema(args or {}, tool["input_schema"])
        if not ok:
            return err_result(name, f"invalid input: {msg}", code="BAD_INPUT")
        try:
            res = tool["handler"](args or {})
            elapsed = int((time.perf_counter() - t) * 1000)
            if isinstance(res, dict) and "ok" in res:
                res.setdefault("tool", name)
                res["elapsed_ms"] = elapsed
                append_jsonl(self.log_path, {"tool": name, "ok": res["ok"],
                                             "ms": elapsed, "args_keys": list((args or {}).keys())})
                return res
            out = ok_result(name, {"value": res}, elapsed)
            append_jsonl(self.log_path, {"tool": name, "ok": True, "ms": elapsed})
            return out
        except Exception as e:  # noqa: BLE001
            elapsed = int((time.perf_counter() - t) * 1000)
            append_jsonl(self.log_path, {"tool": name, "ok": False, "ms": elapsed,
                                         "error": str(e)})
            return err_result(name, str(e), elapsed_ms=elapsed)

    def spec_list(self) -> list[dict[str, Any]]:
        return [{"name": n, "description": v["description"],
                 "inputSchema": {"type": "object", "properties": v["input_schema"]}}
                for n, v in self.tools.items()]

    # ---------- registration ----------
    def _register_all(self) -> None:
        S = {"type": "string", "required": False}
        # connection / project
        self._add("sfm_get_status", "SFM install/run/bridge status", {}, lambda a: {
            "ok": True, "data": self.bridge.get_status()})
        self._add("sfm_connect", "Connect to SFM (honest errors)", {
            "launch": {"type": "boolean", "required": False}}, lambda a: self.bridge.connect(
                launch=bool(a.get("launch", False))))
        self._add("sfm_get_session_info", "Session info", {}, lambda a: {
            "ok": True, "data": self.bridge.get_session_info()})
        self._add("create_animation_project", "Create project from prompt", {
            "prompt": {"type": "string", "required": True},
            "fps": {"type": "integer", "required": False}}, lambda a: {
                "ok": True, "data": self.orch.create_project(
                    a["prompt"], int(a.get("fps", cfg.FPS_DEFAULT)))})
        self._add("get_project_status", "Project status", {
            "project_id": {"type": "string", "required": True}}, lambda a:
            self.orch.get_status(a["project_id"]))

        # story
        self._add("generate_story_and_script", "Story+script from prompt (offline OK)", {
            "prompt": {"type": "string", "required": True}}, lambda a: {
                "ok": True, "data": story_gen.generate_story(a["prompt"])})
        self._add("generate_storyboard", "Storyboard from story", {
            "story": {"type": "object", "required": True},
            "fps": {"type": "integer", "required": False}}, lambda a: {
                "ok": True, "data": story_gen.generate_storyboard(
                    a["story"], int(a.get("fps", 24)))})
        self._add("create_shot_list", "Shot list", {
            "storyboard": {"type": "object", "required": True}}, lambda a: {
                "ok": True, "data": story_gen.create_shot_list(a["storyboard"])})
        self._add("plan_animation_sequence", "Full plan + estimates", {
            "prompt": {"type": "string", "required": True},
            "fps": {"type": "integer", "required": False}}, lambda a: {
                "ok": True, "data": self.orch.plan(a["prompt"], int(a.get("fps", 24)))})

        # assets
        self._add("search_assets", "Search indexed assets", {
            "query": {"type": "string", "required": True},
            "kind": {"type": "string", "required": False},
            "limit": {"type": "integer", "required": False}}, lambda a: {
                "ok": True, "data": self.assets.search(
                    a["query"], a.get("kind", "models"), int(a.get("limit", 20)))})
        self._add("inspect_asset", "Inspect asset path + compat", {
            "asset_path": {"type": "string", "required": True}}, lambda a: {
                "ok": True, "data": {**self.assets.inspect(a["asset_path"]),
                                     "compat": self.assets.check_compat(a["asset_path"])}})
        self._add("find_compatible_motion", "Find motion for asset/action", {
            "asset_path": {"type": "string", "required": True},
            "action": {"type": "string", "required": True}}, lambda a: {
                "ok": True, "data": {"asset": a["asset_path"], "action": a["action"],
                    "rig": anim.validate_rig(a["asset_path"]),
                    "clips": [{"name": f"{a['action']}_clip_01", "source": "built-in keyframes"}]}})
        self._add("prepare_scene_assets", "Scan + missing report", {
            "wanted": {"type": "array", "required": False}}, lambda a: {
                "ok": True, "data": {"index": self.assets.scan(),
                    "missing": self.assets.missing_report(a.get("wanted", []))}})

        # scene
        self._add("create_scene", "Create analytic scene (+queue SFM cmd)", {
            "name": {"type": "string", "required": True},
            "map": {"type": "string", "required": False}}, lambda a: self._create_scene(a))
        self._add("add_model", "Add model to analytic scene (+queue SFM)", {
            "name": {"type": "string", "required": True},
            "asset_path": {"type": "string", "required": True},
            "pos": {"type": "array", "required": False}}, lambda a: self._add_model(a))
        self._add("set_object_transform", "Set pos/rot/scale", {
            "name": {"type": "string", "required": True},
            "pos": {"type": "array", "required": False},
            "rot": {"type": "array", "required": False},
            "scale": {"type": "number", "required": False}}, lambda a: self._set_xform(a))
        self._add("list_scene_objects", "List scene objects", {},
                  lambda a: {"ok": True, "data": _load_scene(self.workdir)})
        self._add("configure_lighting", "Set lighting preset", {
            "preset": {"type": "string", "required": False}}, lambda a: self._lighting(a))

        # animation
        self._add("generate_character_motion", "Keyframes for action", {
            "object": {"type": "string", "required": True},
            "action": {"type": "string", "required": True},
            "start_sec": {"type": "number", "required": True},
            "end_sec": {"type": "number", "required": True},
            "fps": {"type": "integer", "required": False}}, lambda a: anim.generate_keyframes(
                a["object"], a["action"], float(a["start_sec"]), float(a["end_sec"]),
                int(a.get("fps", 24))))
        self._add("apply_motion_clip", "Record clip application", {
            "object": {"type": "string", "required": True},
            "clip": {"type": "string", "required": True}}, lambda a: {
                "ok": True, "data": {"object": a["object"], "clip": a["clip"],
                                     "status": "recorded_analytic",
                                     "note": "SFM-side apply needs in-app script"}})
        self._add("set_animation_keyframe", "Append keyframe to scene", {
            "object": {"type": "string", "required": True},
            "t": {"type": "number", "required": True},
            "pos": {"type": "array", "required": True}}, lambda a: self._add_key(a))
        self._add("assemble_animation_sequence", "Blend motions", {
            "motions": {"type": "array", "required": True}}, lambda a:
                anim.blend(a["motions"]))
        self._add("validate_character_motion", "Space + rig checks", {
            "objects": {"type": "object", "required": True},
            "asset_path": {"type": "string", "required": False}}, lambda a: {
                "ok": True, "data": {"space": anim.check_space(a["objects"]),
                    "rig": anim.validate_rig(a.get("asset_path", "model.mdl"))}})

        # camera + audio
        self._add("create_camera", "Create camera", {
            "name": {"type": "string", "required": True},
            "preset": {"type": "string", "required": False}}, lambda a: self._add_camera(a))
        self._add("direct_cinematic_shots", "Direct cameras for shots", {
            "shots": {"type": "array", "required": True},
            "fps": {"type": "integer", "required": False}}, lambda a: {
                "ok": True, "data": cine.direct_shots(
                    a["shots"], int(a.get("fps", 24)))})
        self._add("generate_dialogue_and_audio", "Dialogue draft", {
            "scenes": {"type": "array", "required": True}}, lambda a:
                audio_dir.generate_dialogue(a["scenes"]))
        self._add("place_audio_cues", "Reserve cue paths", {
            "dialogue": {"type": "array", "required": True},
            "shots": {"type": "array", "required": False}}, lambda a:
                {"ok": True, "data": audio_dir.place_cues(
                    a["dialogue"], a.get("shots", []), self.workdir)})

        # render + QA
        self._add("preview_scene", "Analytic preview (no pixels w/o SFM)", {
            "project_id": {"type": "string", "required": False}}, lambda a: {
                "ok": True, "data": {"scene": _load_scene(self.workdir),
                    "note": "pixel preview needs SFM viewport; analytic dump returned"}})
        self._add("render_animation", "Configure + queue shot renders", {
            "shots": {"type": "array", "required": True},
            "width": {"type": "integer", "required": False},
            "height": {"type": "integer", "required": False},
            "fps": {"type": "integer", "required": False}}, lambda a: self._render(a))
        self._add("get_render_status", "Render state", {}, lambda a: {
            "ok": True, "data": self.renderer.state})
        self._add("review_animation", "QA review", {
            "objects": {"type": "object", "required": True},
            "render_path": {"type": "string", "required": False}}, lambda a: {
                "ok": True, "data": qa_mod.review_scene(
                    a["objects"], _load_scene(self.workdir).get("cameras", []) and [1] or [],
                    a.get("render_path"))})
        self._add("fix_animation_issues", "Fix plan", {
            "review": {"type": "object", "required": True}}, lambda a: {
                "ok": True, "data": qa_mod.plan_fixes(a["review"])})
        self._add("get_final_output", "Verify output file", {
            "path": {"type": "string", "required": True}}, lambda a: {
                "ok": True, "data": self.renderer.verify(a["path"])})
        # full-auto + phase3/4
        self._add("run_full_auto", "15-step prompt->preview->QA->render queue", {
            "prompt": {"type": "string", "required": True},
            "fps": {"type": "integer", "required": False},
            "synthesize_audio": {"type": "boolean", "required": False}}, lambda a: self.orch.run_auto(
                a["prompt"], int(a.get("fps", 24)), bool(a.get("synthesize_audio", True))))
        self._add("resume_project", "Resume from saved project json", {
            "project_id": {"type": "string", "required": True}}, lambda a:
                self.orch.resume(a["project_id"]))
        self._add("apply_auto_fixes", "Lift/separate scene objects", {}, lambda a: {
            "ok": True, "data": self.orch.apply_fixes()})
        self._add("mark_shot_done", "Register manual SFM export", {
            "shot_id": {"type": "integer", "required": True},
            "file": {"type": "string", "required": True}}, lambda a: self.renderer.mark_shot_done(
                int(a["shot_id"]), a["file"]))
        self._add("compose_combat", "Attack-hit-fall chain", {
            "attacker": {"type": "string", "required": True},
            "victim": {"type": "string", "required": True},
            "start_sec": {"type": "number", "required": True}}, lambda a: anim.compose_combat(
                a["attacker"], a["victim"], float(a["start_sec"])))
        self._add("compose_chase", "Chaser-runner with gap check", {
            "chaser": {"type": "string", "required": True},
            "runner": {"type": "string", "required": True},
            "start_sec": {"type": "number", "required": True},
            "end_sec": {"type": "number", "required": True}}, lambda a: anim.compose_chase(
                a["chaser"], a["runner"], float(a["start_sec"]), float(a["end_sec"])))
        self._add("synth_audio_placeholders", "Real wav placeholders (honest labels)", {
            "dialogue": {"type": "array", "required": True},
            "shots": {"type": "array", "required": False}}, lambda a: {
                "ok": True, "data": audio_dir.place_cues(
                    a["dialogue"], a.get("shots", []), self.workdir, synthesize=True)})
        self._add("validate_wav", "Validate wav file", {
            "path": {"type": "string", "required": True}}, lambda a: audio_dir.validate_wav(a["path"]))
        self._add("combine_shots", "ffmpeg concat of exported shots", {
            "inputs": {"type": "array", "required": True},
            "output": {"type": "string", "required": True}}, lambda a: self.renderer.combine(
                a["inputs"], a["output"]))
        _ = S

    # ---- scene helpers ----
    def _create_scene(self, a: dict[str, Any]) -> dict[str, Any]:
        scene = {"name": a["name"], "map": a.get("map", "tf/maps/ctf_2fort.bsp"),
                 "objects": {}, "cameras": {}, "lights": {"preset": "default"},
                 "keyframes": []}
        _save_scene(self.workdir, scene)
        q = self.bridge.enqueue("create_scene", {"name": a["name"]})
        return {"ok": True, "data": {"scene": scene, "sfm_queue": q}}

    def _add_model(self, a: dict[str, Any]) -> dict[str, Any]:
        scene = _load_scene(self.workdir)
        chk = self.assets.inspect(a["asset_path"])
        if not chk.get("ok"):
            return {"ok": False, "error": chk,
                    "hint": "run prepare_scene_assets / search_assets first"}
        scene["objects"][a["name"]] = {"asset": a["asset_path"],
                                       "pos": a.get("pos", [0, 0, 0]),
                                       "rot": [0, 0, 0], "scale": 1.0}
        _save_scene(self.workdir, scene)
        q = self.bridge.enqueue("add_model", a)
        return {"ok": True, "data": {"object": scene["objects"][a["name"]], "sfm_queue": q}}

    def _set_xform(self, a: dict[str, Any]) -> dict[str, Any]:
        scene = _load_scene(self.workdir)
        if a["name"] not in scene["objects"] and a["name"] not in scene["cameras"]:
            return {"ok": False, "error": f"unknown object: {a['name']}",
                    "hint": "call list_scene_objects"}
        tgt = scene["objects"].get(a["name"]) or scene["cameras"].get(a["name"])
        if "pos" in a and a["pos"] is not None:
            tgt["pos"] = a["pos"]
        if "rot" in a and a["rot"] is not None:
            tgt["rot"] = a["rot"]
        if "scale" in a and a["scale"] is not None:
            tgt["scale"] = a["scale"]
        _save_scene(self.workdir, scene)
        q = self.bridge.enqueue("set_transform", a)
        return {"ok": True, "data": {"object": tgt, "sfm_queue": q}}

    def _lighting(self, a: dict[str, Any]) -> dict[str, Any]:
        scene = _load_scene(self.workdir)
        scene["lights"] = {"preset": a.get("preset", "war_dusk")}
        _save_scene(self.workdir, scene)
        return {"ok": True, "data": scene["lights"]}

    def _add_key(self, a: dict[str, Any]) -> dict[str, Any]:
        scene = _load_scene(self.workdir)
        scene.setdefault("keyframes", []).append(
            {"object": a["object"], "t": a["t"], "pos": a["pos"]})
        _save_scene(self.workdir, scene)
        return {"ok": True, "data": {"count": len(scene["keyframes"])}}

    def _add_camera(self, a: dict[str, Any]) -> dict[str, Any]:
        scene = _load_scene(self.workdir)
        preset = cine.SHOT_PRESETS.get(a.get("preset", "wide"), cine.SHOT_PRESETS["wide"])
        scene["cameras"][a["name"]] = {"preset": a.get("preset", "wide"), **preset,
                                       "pos": [preset["dist"], 0, preset["height"]]}
        _save_scene(self.workdir, scene)
        q = self.bridge.enqueue("create_camera", a)
        return {"ok": True, "data": {"camera": scene["cameras"][a["name"]], "sfm_queue": q}}

    def _render(self, a: dict[str, Any]) -> dict[str, Any]:
        fps = int(a.get("fps", 24))
        self.renderer.configure(int(a.get("width", 1280)),
                                int(a.get("height", 720)), fps)
        out = []
        for s in a["shots"]:
            out.append(self.renderer.render_shot(int(s.get("shot_id", 1)),
                                                 int(s.get("start_sec", 0) * fps),
                                                 int(s.get("end_sec", 1) * fps)))
        return {"ok": True, "data": {"shots": out, "state": self.renderer.state}}
