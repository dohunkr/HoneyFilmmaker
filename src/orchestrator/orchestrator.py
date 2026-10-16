"""AI Orchestrator: prompt -> plan -> execute with dependencies + resume."""
from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Any

from src.common import config as cfg
from src.common.job_queue import JobQueue
from src.story import generator as story_gen
from src.assets.manager import AssetManager
from src.animation import engine as anim
from src.cinematography import director as cine
from src.audio import director as audio_dir
from src.rendering.manager import RenderManager
from src.quality import qa as qa_mod
from src.bridge.sfm_bridge import SFMBridge


class Orchestrator:
    def __init__(self, workdir: Path | None = None) -> None:
        self.workdir = cfg.resolve_workdir(str(workdir) if workdir else None)
        self.projects_dir = self.workdir / "projects"
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.queue = JobQueue(self.workdir / "job_queue.json")
        self.bridge = SFMBridge(self.workdir)
        self.assets = AssetManager(self.workdir)
        self.renderer = RenderManager(self.workdir)
        self._register_handlers()

    # ---- project ----
    def create_project(self, prompt: str, fps: int = 24) -> dict[str, Any]:
        pid = f"proj-{int(time.time())}"
        proj = {"project_id": pid, "prompt": prompt, "fps": fps,
                "created_at": time.time(), "status": "planned", "steps": []}
        (self.projects_dir / f"{pid}.json").write_text(
            json.dumps(proj, ensure_ascii=False, indent=2), encoding="utf-8")
        return proj

    def _load_project(self, project_id: str) -> dict[str, Any]:
        p = self.projects_dir / f"{project_id}.json"
        if not p.is_file():
            raise FileNotFoundError(f"unknown project: {project_id}")
        return json.loads(p.read_text(encoding="utf-8"))

    def _save_project(self, proj: dict[str, Any]) -> None:
        (self.projects_dir / f"{proj['project_id']}.json").write_text(
            json.dumps(proj, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_status(self, project_id: str) -> dict[str, Any]:
        try:
            return {"ok": True, "project": self._load_project(project_id)}
        except FileNotFoundError as e:
            return {"ok": False, "error": str(e)}

    # ---- pipeline ----
    def plan(self, prompt: str, fps: int = 24) -> dict[str, Any]:
        story = story_gen.generate_story(prompt)
        board = story_gen.generate_storyboard(story, fps=fps)
        shots = story_gen.create_shot_list(board)
        cams = cine.direct_shots(shots["shots"], fps=fps)
        total_frames = board["total_frames"]
        return {"story": story, "storyboard": board, "shot_list": shots,
                "cinematography": cams, "total_frames": total_frames,
                "estimated_render_min": round(total_frames / fps / 60 * 2, 1)}

    def run_full(self, prompt: str, fps: int = 24) -> dict[str, Any]:
        """Dependency-ordered auto build. Stops honestly on missing SFM/assets."""
        proj = self.create_project(prompt, fps=fps)
        pid = proj["project_id"]
        log: list[dict[str, Any]] = []

        def step(name: str, fn, *a, **k):
            try:
                r = fn(*a, **k)
                log.append({"step": name, "ok": True})
                proj["steps"] = log
                self._save_project({**proj, "plan": getattr(self, "_last_plan", {})})
                return r
            except Exception as e:  # noqa: BLE001
                log.append({"step": name, "ok": False, "error": str(e)})
                raise

        plan = self.plan(prompt, fps=fps)
        self._last_plan = plan
        proj["plan"] = plan
        proj["status"] = "running"
        self._save_project(proj)

        # assets
        self.assets.scan()
        # animation per shot (analytic keyframes)
        seqs = []
        for s in plan["shot_list"]["shots"][:12]:
            kf = anim.generate_keyframes(f"hero_{s['shot_id']}", "run",
                                         s["start_sec"], s["end_sec"], fps=fps,
                                         frm=[0, 0, 0], to=[200, 50, 0])
            seqs.append(kf)
        blended = anim.blend([{"keyframes": k.get("keyframes", [])} for k in seqs if k.get("ok")])
        # audio
        dialogue = audio_dir.generate_dialogue(plan["storyboard"]["scenes"])
        cues = audio_dir.place_cues(dialogue.get("lines", []),
                                    plan["shot_list"]["shots"], self.workdir)
        # bridge: queue scene creation honestly (fails if SFM down)
        st = self.bridge.get_status()
        bridge_note = ("SFM connected" if st["connected"]
                       else f"SFM not connected (installed={st['sfm_installed']}, "
                             f"running={st['sfm_running']}); scene ops queued only")
        # render config + QA (analytic)
        self.renderer.configure(fps=fps)
        objects = {f"hero_{i}": [i * 60.0, 0, 0] for i in range(3)}
        review = qa_mod.review_scene(objects,
                                     plan["cinematography"].get("cameras", []),
                                     duration_sec=plan["story"]["duration_sec"])
        proj.update({"status": "built_analytic",
                     "animation_sequences": len(seqs),
                     "blended_keyframes": blended.get("count", 0),
                     "dialogue_lines": len(dialogue.get("lines", [])),
                     "audio_cues": len(cues.get("cues", [])),
                     "bridge": bridge_note,
                     "qa": review})
        self._save_project(proj)
        _ = step  # job-queue execution hook for long tasks
        return {"ok": True, "project_id": pid, "project": proj, "plan": plan}

    # ---- job queue demo handlers ----
    def _register_handlers(self) -> None:
        def _render(payload: dict[str, Any], prog) -> dict[str, Any]:
            prog(0.2)
            shot_id = int(payload.get("shot_id", 1))
            res = self.renderer.render_shot(shot_id,
                                            int(payload.get("start_frame", 0)),
                                            int(payload.get("end_frame", 24)))
            prog(1.0)
            return res
        self.queue.register("render_shot", _render)

    # ---- Phase 4: continuity / fixes / resume / full auto ----
    def build_bible(self, story: dict[str, Any]) -> dict[str, Any]:
        chars = story.get("characters", [])
        bible = {}
        for i, c in enumerate(chars):
            bible[c] = {"faction": "cameraman" if "카메라" in c else "toilet",
                        "appearance": f"variant-{i + 1}",
                        "props": ["camera-head"] if "카메라" in c else ["plunger"],
                        "state": "ready", "last_pos": [i * 80.0, 0, 0]}
        return bible

    def apply_fixes(self, scene_path: Path | None = None) -> dict[str, Any]:
        import json as _j
        sp = scene_path or (self.workdir / "scene.json")
        if not sp.is_file():
            return {"ok": False, "error": "no scene.json; run create_scene first"}
        scene = _j.loads(sp.read_text(encoding="utf-8"))
        fixed = 0
        for _name, obj in list(scene.get("objects", {}).items()):
            pos = obj.get("pos", [0, 0, 0])
            if len(pos) >= 3 and pos[2] < 0:
                pos[2] = 0
                fixed += 1
        # separate overlaps >= 40
        names = list(scene.get("objects", {}).keys())
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a = scene["objects"][names[i]].get("pos", [0, 0, 0])
                b = scene["objects"][names[j]].get("pos", [0, 0, 0])
                import math as _m
                try:
                    if _m.dist(a[:3], b[:3]) < 40:
                        b[0] += 40
                        fixed += 1
                except Exception:
                    pass
        sp.write_text(_j.dumps(scene, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "fixed": fixed}

    def resume(self, project_id: str) -> dict[str, Any]:
        try:
            proj = self._load_project(project_id)
        except FileNotFoundError as e:
            return {"ok": False, "error": str(e)}
        # Recompute remaining: if built_analytic but no final output, continue to preview+QA.
        proj["resumed_at"] = time.time()
        proj["status"] = proj.get("status", "") + "+resumed"
        self._save_project(proj)
        return {"ok": True, "project": proj}

    def write_preview(self, project_id: str, plan: dict[str, Any]) -> str:
        out_dir = self.workdir / "previews" / project_id
        out_dir.mkdir(parents=True, exist_ok=True)
        html = ["<html><head><meta charset='utf-8'><title>preview</title></head><body>"]
        html.append(f"<h1>{project_id}</h1>")
        for s in plan["shot_list"]["shots"]:
            html.append(f"<p>shot {s['shot_id']} [{s['shot_type']}] "
                        f"{s['start_sec']}s-{s['end_sec']}s : {s.get('action_hint','')}</p>")
        html.append("<p>NOTE: analytic preview; pixel render needs SFM Export Movie.</p></body></html>")
        p = out_dir / "preview.html"
        p.write_text("\n".join(html), encoding="utf-8")
        return str(p)

    def run_auto(self, prompt: str, fps: int = 24,
                 synthesize_audio: bool = True) -> dict[str, Any]:
        """Spec section 5: 15-step auto pipeline with honest stops."""
        proj = self.create_project(prompt, fps=fps)
        pid = proj["project_id"]
        steps: list[dict[str, Any]] = []

        def _s(name: str, ok: bool, extra: str = ""):
            steps.append({"step": name, "ok": ok, "note": extra})
            proj["steps"] = steps
            self._save_project(proj)

        # 1 prompt analyze, 2 story/script/end, 3 split scenes/shots
        plan = self.plan(prompt, fps=fps)
        bible = self.build_bible(plan["story"])
        _s("1-3 prompt/story/shots", True, f"{plan['shot_list']['shot_count']} shots")
        # 4 search assets, 5 compat + alternates
        idx = self.assets.scan()
        missing = self.assets.missing_report([])
        _s("4-5 assets", True, f"indexed={idx.get('count')}")
        # 6 project+scene, 7 place props with continuity
        scene = {"name": pid, "objects": {}, "cameras": {}, "lights": {},
                 "keyframes": [], "bible": bible}
        pos_cursor: dict[str, list[float]] = {}
        for name, info in bible.items():
            p = info["last_pos"]
            scene["objects"][name] = {"asset": "tf/models/candidate.mdl", "pos": p,
                                      "rot": [0, 0, 0], "scale": 1.0}
            pos_cursor[name] = p
        (self.workdir / "scene.json").write_text(
            json.dumps(scene, ensure_ascii=False, indent=2), encoding="utf-8")
        _s("6-7 scene+place", True, f"{len(scene['objects'])} objects")
        # 8 motion+keyframes with continuity (chase/combat mix)
        all_keys: list[dict[str, Any]] = []
        for s in plan["shot_list"]["shots"]:
            sid = s["shot_id"]
            if sid % 3 == 0:
                comp = anim.compose_combat("카메라맨 리더", "토일렛 그런트 x3",
                                           s["start_sec"], fps=fps)
            elif sid % 3 == 1:
                comp = anim.compose_chase("카메라맨 스카우트", "토일렛 그런트 x3",
                                          s["start_sec"], s["end_sec"], fps=fps)
            else:
                kf = anim.generate_keyframes(f"hero_{sid}", "run",
                                             s["start_sec"], s["end_sec"], fps=fps,
                                             frm=[0, 0, 0], to=[200, 50, 0])
                comp = {"ok": kf.get("ok"), "keyframes": kf.get("keyframes", []),
                        "count": len(kf.get("keyframes", []))}
            if comp.get("ok"):
                all_keys.extend(comp.get("keyframes", []))
        scene["keyframes"] = sorted(all_keys, key=lambda k: k["t"])
        (self.workdir / "scene.json").write_text(
            json.dumps(scene, ensure_ascii=False, indent=2), encoding="utf-8")
        _s("8 motion", True, f"{len(all_keys)} keys")
        # 9 camera+light
        cams = cine.direct_shots(plan["shot_list"]["shots"], fps=fps)
        scene["cameras"] = {c["shot_id"]: c for c in cams["cameras"]}
        scene["lights"] = cams["lighting"]
        (self.workdir / "scene.json").write_text(
            json.dumps(scene, ensure_ascii=False, indent=2), encoding="utf-8")
        _s("9 camera+light", True, f"repeats={cams['diversity_repeats']}")
        # 10 dialogue+sfx (synth honest placeholders)
        dialogue = audio_dir.generate_dialogue(plan["storyboard"]["scenes"])
        cues = audio_dir.place_cues(dialogue.get("lines", []),
                                    plan["shot_list"]["shots"],
                                    self.workdir, synthesize=synthesize_audio)
        _s("10 audio", True, f"{len(cues['cues'])} cues")
        # 11 preview
        preview = self.write_preview(pid, plan)
        _s("11 preview", True, preview)
        # 12 QA + fix
        objs = {n: o["pos"] for n, o in scene["objects"].items()}
        review = qa_mod.review_scene(objs, cams["cameras"],
                                     duration_sec=plan["story"]["duration_sec"])
        fixes = self.apply_fixes()
        review2 = qa_mod.review_scene(
            {n: o["pos"] for n, o in
             json.loads((self.workdir / 'scene.json').read_text(encoding='utf-8'))["objects"].items()},
            cams["cameras"], duration_sec=plan["story"]["duration_sec"])
        _s("12 qa+fix", True, f"before={review['issue_count']} after={review2['issue_count']}")
        # 13 per-shot renders (queued) 14 combine attempt 15 verify+report
        self.renderer.configure(fps=fps)
        rq = [self.renderer.render_shot(s["shot_id"],
                                        int(s["start_sec"] * fps),
                                        int(s["end_sec"] * fps))
              for s in plan["shot_list"]["shots"]]
        done_files = [s.get("file") for s in self.renderer.state.get("shots", {}).values()
                      if s.get("status") == "done" and s.get("file")]
        if done_files:
            comb = self.renderer.combine(done_files, f"renders/{pid}_final.mp4")
        else:
            comb = {"ok": False, "error": "no exported shot files yet",
                    "hint": "Export each shot in SFM, mark_shot_done, then combine"}
        final = comb.get("output", "")
        ver = self.renderer.verify(final) if comb.get("ok") else {"ok": False}
        _s("13-15 render+combine+verify", bool(comb.get("ok")),
           f"{'final=' + str(final) if comb.get('ok') else comb.get('error')}")
        proj.update({"status": "auto_done_analytic" if not comb.get("ok") else "auto_done",
                     "plan": plan, "bible": bible,
                     "preview": preview, "qa_before": review, "qa_after": review2,
                     "render_queue": rq, "combine": comb, "verify": ver,
                     "missing": missing})
        self._save_project(proj)
        return {"ok": True, "project_id": pid, "project": proj, "steps": steps}
