# -*- coding: utf-8 -*-
# SFM in-app bridge poller - Python 2.7 compatible (SFM embedded interpreter).
# Install: In SFM, open Script Editor -> Open this file -> Run.
# It polls <workdir>/bridge_queue/inbox/*.json every 1s and writes results
# to <workdir>/bridge_queue/outbox/<id>.json + heartbeat.json.
#
# NOTE: SFM exposes `sfm`, `vs`, `dm` modules only inside SFM. This script
# degrades gracefully: if those modules are missing it still moves files
# so the queue does not grow unbounded, marking unsupported ops honestly.
import os
import sys
import json
import time
import traceback

try:
    WORKDIR = os.environ.get("HONEY_WORKDIR", r"D:\Github\HoneyFilmmaker\workdir")
except Exception:
    WORKDIR = r"D:\Github\HoneyFilmmaker\workdir"

QUEUE = os.path.join(WORKDIR, "bridge_queue")
INBOX = os.path.join(QUEUE, "inbox")
OUTBOX = os.path.join(QUEUE, "outbox")
HEARTBEAT = os.path.join(QUEUE, "heartbeat.json")
SESSION = os.path.join(QUEUE, "last_session.json")

HAVE_SFM = False
try:
    import sfm  # noqa: F401
    HAVE_SFM = True
except Exception:
    HAVE_SFM = False


def ensure_dirs():
    for d in (QUEUE, INBOX, OUTBOX):
        if not os.path.isdir(d):
            os.makedirs(d)


def heartbeat():
    try:
        atomic_write(HEARTBEAT, {"ts": time.time(), "have_sfm": HAVE_SFM})
    except Exception:
        pass


def sfm_find_shot(name=None):
    """Get a shot without relying on UI selection.
    Order: sfm.GetCurrentShot() -> sfmApp.GetShots()[0] -> sfmApp.GetShots()[name].
    Also try sfmApp.GetShotAtCurrentTime() (verified API) as a third source."""
    shot = None
    try:
        import sfm
        shot = sfm.GetCurrentShot()
    except Exception:
        shot = None
    if shot is not None:
        return shot, "sfm.GetCurrentShot"
    try:
        import sfmApp
        if not sfmApp.HasDocument():
            return None, "no document open"
        # current-time shot first (what the UI timeline points at)
        try:
            s = sfmApp.GetShotAtCurrentTime()
            if s is not None:
                return s, "sfmApp.GetShotAtCurrentTime"
        except Exception:
            pass
        shots = sfmApp.GetShots()
    except Exception as e:
        return None, "sfmApp.GetShots failed: %s" % e
    if not shots:
        return None, "no shots in document"
    if name:
        for s in shots:
            try:
                if str(s.GetName()) == str(name):
                    return s, "sfmApp.GetShots[name=%s]" % name
            except Exception:
                continue
    return shots[0], "sfmApp.GetShots[0]"


def sfm_current_shot_name():
    """Ask SFM which shot the UI points at, and make it current if possible."""
    info = {}
    try:
        import sfm
        cur = sfm.GetCurrentShot()
        info["GetCurrentShot"] = None if cur is None else str(cur.GetName())
    except Exception as e:
        info["GetCurrentShot_error"] = str(e)[:120]
    try:
        import sfmApp
        s = sfmApp.GetShotAtCurrentTime()
        info["GetShotAtCurrentTime"] = None if s is None else str(s.GetName())
        info["timeline_mode"] = str(sfmApp.GetTimelineMode())
    except Exception as e:
        info["GetShotAtCurrentTime_error"] = str(e)[:120]
    return info


def sfm_model_path_candidates(asset_path):
    """SFM loads models from the game content tree.
    Verified from Valve's own session files (tf_movies/.../mtt_soldier.dmx):
    the working form is "models/player/hwm/<class>.mdl" (HWM only).
    Non-HWM paths return None from CreateModel."""
    raw = str(asset_path).replace("\\", "/").strip()
    cands = [raw]
    parts = raw.split("/")
    fname = parts[-1]
    folder = parts[-2] if len(parts) >= 2 else ""
    if folder and folder != "hwm":
        # insert hwm segment if a class model is given
        cands.append(raw[:raw.rfind("/") + 1] + "hwm/" + fname)
    if fname.startswith("bot_"):
        cands.append("models/bots/" + fname)
    else:
        cands.append("models/player/hwm/" + fname)
    cands.append("models/player/hwm/" + fname)
    try:
        import sfm
        gd = sfm.GetSteamDir() if hasattr(sfm, "GetSteamDir") else None
    except Exception:
        gd = None
    if gd:
        cands.append(str(gd) + "/" + raw)
    out = []
    for c in cands:
        if c and c not in out:
            out.append(c)
    return out


def sfm_probe_create_model(path="models/player/scout.mdl"):
    """Discover CreateModel's real signature WITHOUT crashing SFM.
    Only 1..3 args are tried (0 args crashes the native binding)."""
    res = []
    try:
        import sfm
    except Exception:
        return {"ok": False, "error": "no sfm module"}
    variants = [
        ("1arg_path", (path,)),
        ("2arg_name_path", ("PROBE_MODEL", path)),
        ("2arg_path_name", (path, "PROBE_MODEL")),
        ("3arg_name_path_x", ("PROBE_MODEL", path, "")),
    ]
    for label, args in variants:
        try:
            m = sfm.CreateModel(*args)
            res.append({"variant": label, "n": len(args),
                        "result": "OK" if m is not None else "None"})
            if m is not None:
                return {"ok": True, "winner": label, "n": len(args),
                        "results": res}
        except Exception as e:
            res.append({"variant": label, "n": len(args), "error": str(e)[:140]})
    return {"ok": False, "error": "no variant loaded", "results": res}


def sfm_path_candidates_all():
    """Every plausible path form SFM might accept, plus every arity 1..2.
    Verified reference (Valve tf_movies sessions): models/player/hwm/scout.mdl
    relative to the *game* dir, which for TF2 content means tf/... .
    """
    rel = ["models/player/hwm/scout.mdl", "player/hwm/scout.mdl",
           "hwm/scout.mdl", "scout.mdl", "models/player/scout.mdl",
           "player/scout.mdl", "models/scout.mdl"]
    out = []
    for r in rel:
        out.append(r)
        out.append("tf/" + r)
        out.append("models/" + r)
        out.append("tf/models/" + r.split("/", 1)[-1] if "/" in r else r)
        out.append("game/" + r)
        out.append("usermod/" + r)
    for r in list(rel):
        out.append(r.replace("/", "\\"))
        out.append("tf\\" + r.replace("/", "\\"))
    gd = "D:/SteamLibrary/steamapps/common/SourceFilmmaker/game"
    for base in [gd, gd + "/tf"]:
        for r in ["models/player/hwm/scout.mdl", "player/hwm/scout.mdl",
                  "hwm/scout.mdl", "scout.mdl"]:
            out.append(base + "/" + r)
    seen = set()
    res = []
    for c in out:
        if c and c not in seen:
            seen.add(c)
            res.append(c)
    return res


def sfm_probe_paths():
    """Try many path forms x arity 1..2, write results to disk.
    Only string args are used, so the native binding cannot crash on arity."""
    import traceback
    res = {"tries": [], "winner": None, "ctx": {}}
    out = os.path.join(QUEUE, "probe_paths.json")
    try:
        import sfm
    except Exception:
        return {"ok": False, "error": "no sfm module"}
    res["ctx"]["shot_state"] = sfm_current_shot_name()
    # 1) does the CURRENT shot matter? try with a shot we can obtain
    shot, how = sfm_find_shot()
    res["ctx"]["shot_source"] = how
    res["ctx"]["shot_name"] = None if shot is None else str(shot.GetName())
    cands = sfm_path_candidates_all()
    for p in cands:
        entry = {"path": p}
        try:
            m = sfm.CreateModel(p)
            entry["r1"] = "OK" if m is not None else "None"
        except Exception as e:
            entry["r1"] = "ERR " + str(e)[:90]
        if entry["r1"] == "OK":
            res["tries"].append(entry)
            res["winner"] = {"path": p, "arity": 1}
            break
        res["tries"].append(entry)
    if res["winner"] is None:
        for p in cands[:20]:
            entry = {"path": p, "arity": 2}
            try:
                m = sfm.CreateModel("PROBE_MODEL", p)
                entry["r2"] = "OK" if m is not None else "None"
            except Exception as e:
                entry["r2"] = "ERR " + str(e)[:90]
            res["tries"].append(entry)
            if entry["r2"] == "OK":
                res["winner"] = {"path": p, "arity": 2, "name": "PROBE_MODEL"}
                break
    # 3) does an animation set need to exist first? try the valve order:
    #    shot -> CreateModel -> CreateAnimationSet(target=model)
    if res["winner"] is None and shot is not None:
        try:
            m = sfm.CreateModel("models/player/hwm/scout.mdl")
            res["ctx"]["with_shot_create"] = "OK" if m is not None else "None"
            if m is not None:
                a = sfm.CreateAnimationSet("PROBE", target=m)
                res["ctx"]["animset"] = "OK" if a is not None else "None"
        except Exception as e:
            res["ctx"]["with_shot_error"] = str(e)[:140]
    try:
        with open(out, "w") as f:
            json.dump(res, f, indent=2)
    except Exception:
        pass
    print("[sfm_bridge] probe_paths winner=%s ctx=%s" % (res["winner"], res["ctx"]))
    return {"ok": True, "winner": res["winner"], "ctx": res["ctx"],
            "tried_count": len(res["tries"]), "file": out}


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _child_list(el):
    """Best-effort child access for the vs datamodel."""
    out = []
    ch = _safe(lambda: el.children)
    if ch is None:
        return out
    try:
        for c in ch:
            out.append(c)
            if len(out) > 400:
                break
    except Exception:
        pass
    return out


def _elem_info(el):
    info = {"name": _safe(lambda: str(el.GetName()), "?"),
            "type": _safe(lambda: str(el.GetTypeName()), "?")}
    for attr in ["model", "modelPath", "path", "filename"]:
        v = _safe(lambda a=attr: el.GetAttributeValue(a))
        if v is not None:
            info[attr] = str(v)
    return info


def sfm_diagnose():
    """Read-only introspection of the SFM document.
    NEVER calls CreateModel: a wrong arity crashes SFM natively.
    Writes partial results to disk as it goes so a crash still leaves data."""
    import traceback
    rep = {"ts": time.time(), "have_sfm": HAVE_SFM, "safe": True}
    out = os.path.join(QUEUE, "diagnose.json")

    def flush():
        try:
            with open(out, "w") as f:
                json.dump(rep, f, indent=2)
        except Exception:
            pass

    flush()
    try:
        import sfm
        rep["sfm_fns_all"] = [x for x in dir(sfm) if not x.startswith("_")]
    except Exception:
        rep["sfm_error"] = traceback.format_exc(limit=2)
    flush()
    try:
        import sfmApp
        rep["sfmApp_fns"] = [x for x in dir(sfmApp) if not x.startswith("_")]
        rep["has_document"] = _safe(lambda: bool(sfmApp.HasDocument()))
        shots = _safe(lambda: list(sfmApp.GetShots())) or []
        rep["shots"] = [str(_safe(lambda s=s: s.GetName(), "?")) for s in shots]
    except Exception:
        rep["sfmApp_error"] = traceback.format_exc(limit=2)
    flush()

    # Walk the document to find existing model paths SFM itself created.
    found = []
    roots = []
    try:
        import sfmApp
        root = _safe(lambda: sfmApp.GetDocumentRoot())
        if root is not None:
            roots.append(root)
    except Exception:
        pass
    try:
        import vs
        sr = _safe(lambda: vs.GetStudioRoot())
        if sr is not None:
            roots.append(sr)
    except Exception:
        pass
    rep["root_count"] = len(roots)
    seen = set()
    stack = list(roots)
    depth = 0
    while stack and depth < 4000:
        depth += 1
        el = stack.pop()
        try:
            key = id(el)
        except Exception:
            key = None
        if key is not None:
            if key in seen:
                continue
            seen.add(key)
        info = _elem_info(el)
        if info.get("model") or "Model" in info.get("type", ""):
            found.append(info)
        stack.extend(_child_list(el))
    rep["elements_walked"] = depth
    rep["models_found"] = found[:40]
    flush()
    print("[sfm_bridge] diagnose written to %s" % out)
    return rep


def sfm_save_session():
    """Save the open SFM document so work is never lost to a crash."""
    try:
        import sfmApp
    except Exception:
        return {"ok": False, "error": "no sfmApp module"}
    if not _safe(lambda: bool(sfmApp.HasDocument())):
        return {"ok": False, "error": "no document open"}
    try:
        r = sfmApp.SaveDocument()
        return {"ok": True, "saved": True, "result": str(r)[:120]}
    except Exception as e:
        return {"ok": False, "error": "SaveDocument failed: %s" % e}


def sfm_place_model(name, asset_path, pos=None, shot_name=None):
    """Real placement via Valve's sfmUtils pattern. Returns dict result."""
    try:
        import sfm
    except Exception:
        return {"ok": False, "error": "no sfm module (run inside SFM)"}
    try:
        import vs
    except Exception:
        return {"ok": False, "error": "no vs module (run inside SFM)"}
    shot, how = sfm_find_shot(shot_name)
    if shot is None:
        return {"ok": False, "code": "NO_SHOT",
                "error": "no shot available (%s)" % how,
                "hint": "Open a session with a shot, or create one: "
                        "Timeline > right-click > Add Shot"}
    cands = sfm_model_path_candidates(asset_path)
    model = None
    used = None
    tried = []
    for c in cands:
        try:
            m = sfm.CreateModel(c)
        except Exception as e:
            tried.append("%s -> raised %s" % (c, str(e)[:80]))
            continue
        tried.append("%s -> %s" % (c, "None" if m is None else "OK"))
        if m is not None:
            model = m
            used = c
            break
    if model is None:
        return {"ok": False, "error": "CreateModel failed for all path forms",
                "tried": tried,
                "hint": "Use search_assets to get the exact path, or create the "
                        "animation set manually in SFM"}
    try:
        animSet = sfm.CreateAnimationSet(str(name), target=model)
    except Exception as e:
        return {"ok": False, "error": "CreateAnimationSet raised: %s" % e,
                "note": "model object was created", "path_used": used}
    try:
        dag = vs.CreateElement("DmeDag", str(name), shot.GetFileId())
        dag.AddChild(model)
        shot.scene.AddChild(dag)
    except Exception as e:
        return {"ok": False, "error": "dag attach raised: %s" % e,
                "note": "model+animSet exist", "path_used": used}
    moved = None
    if pos is not None:
        try:
            sfm.SelectDag(dag)
            sfm.Move(float(pos[0]), float(pos[1]), float(pos[2]))
            moved = [float(pos[0]), float(pos[1]), float(pos[2])]
        except Exception as e:
            moved = "Move failed: %s (placed at origin)" % e
    saved = sfm_save_session()
    return {"ok": True, "name": name, "path": used, "shot": how,
            "animSet": bool(animSet is not None), "moved": moved,
            "saved": saved.get("ok"), "save_error": saved.get("error", "")}


def sfm_set_transform(name, pos=None, rot=None):
    try:
        import sfm
    except Exception:
        return {"ok": False, "error": "no sfm module (run inside SFM)"}
    try:
        dag = sfm.FindDag(str(name))
    except Exception as e:
        return {"ok": False, "error": "FindDag raised: %s" % e}
    if dag is None:
        return {"ok": False, "error": "dag not found: %s" % name}
    out = {"ok": True, "name": name}
    if pos is not None:
        try:
            sfm.SelectDag(dag)
            sfm.Move(float(pos[0]), float(pos[1]), float(pos[2]))
            out["pos"] = list(pos)
        except Exception as e:
            out["ok"] = False
            out["move_error"] = str(e)
    if rot is not None:
        try:
            sfm.SelectDag(dag)
            sfm.Rotate(float(rot[0]), float(rot[1]), float(rot[2]))
            out["rot"] = list(rot)
        except Exception as e:
            out["ok"] = False
            out["rotate_error"] = str(e)
    return out


def handle(cmd):
    name = cmd.get("command")
    params = cmd.get("params", {})
    if not HAVE_SFM:
        return {"id": cmd.get("id"), "ok": False,
                "error": "SFM python modules (sfm/vs/dm) not available in this interpreter",
                "hint": "Run this script inside SFM Script Editor, not standalone python"}
    # Verified SFM API surface is version-dependent; do minimal safe ops here.
    # Full scene/mdl/camera ops require an open SFM session with shots.
    # We acknowledge receipt and echo params so MCP side can track progress
    # without faking scene mutation.
    try:
        import sfm as sfm_mod
        session = None
        try:
            session = sfm_mod.GetCurrentSession()
        except Exception:
            session = None
        info = {"session_open": bool(session)}
        try:
            atomic_write(SESSION, {"connected": True, "have_sfm": True,
                                   "session_open": bool(session), "ts": time.time(),
                                   "last_command": name, "last_params": params})
        except Exception:
            pass
        if name == "ping":
            return {"id": cmd.get("id"), "ok": True, "result": info}
        if name == "get_session":
            return {"id": cmd.get("id"), "ok": True, "result": info}
        if name == "add_model":
            r = sfm_place_model(params.get("name", "model"),
                                params.get("asset_path", ""),
                                params.get("pos"),
                                params.get("shot"))
            r["id"] = cmd.get("id")
            r["session"] = info
            return r
        if name == "diagnose":
            r = sfm_diagnose()
            r["id"] = cmd.get("id")
            r["ok"] = True
            return r
        if name == "probe_model":
            r = sfm_probe_create_model(params.get("path",
                                                  "models/player/scout.mdl"))
            r["id"] = cmd.get("id")
            return r
        if name == "probe_paths":
            r = sfm_probe_paths()
            r["id"] = cmd.get("id")
            return r
        if name == "set_transform":
            r = sfm_set_transform(params.get("name", ""),
                                  params.get("pos"), params.get("rot"))
            r["id"] = cmd.get("id")
            r["session"] = info
            return r
        if name in ("create_scene", "create_camera"):
            return {"id": cmd.get("id"), "ok": False,
                    "error": "command '%s' has no verified SFM API" % name,
                    "hint": "create_scene: load the map manually in SFM. "
                            "create_camera: create the camera manually for now.",
                    "received_params": params, "session": info}
        # Mutating commands: require manual confirmation inside SFM for safety.
        # Operator should extend these branches with validated sfm/vs/dm calls.
        return {"id": cmd.get("id"), "ok": False,
                "error": "command '%s' needs session-specific implementation" % name,
                "hint": "Extend sfm_in_app.py handle() with validated sfm/vs/dm calls; "
                        "see docs/SFM_INTERFACE_RESEARCH.md",
                "received_params": params, "session": info}
    except Exception:
        return {"id": cmd.get("id"), "ok": False,
                "error": traceback.format_exc(limit=3)}


def atomic_write(path, data):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f)
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
        os.rename(tmp, path)
    except Exception:
        pass


def poll_once():
    """Process the whole queue once and return. No loops, no threads,
    no sleeps: SFM Script Editor runs snippets synchronously, so this
    returns control in seconds. Submit again for the next batch."""
    ensure_dirs()
    heartbeat()
    done, failed = 0, 0
    try:
        names = sorted(os.listdir(INBOX))
    except Exception:
        names = []
    for n in names:
        if not n.endswith(".json"):
            continue
        p = os.path.join(INBOX, n)
        try:
            with open(p, "r") as f:
                cmd = json.load(f)
        except Exception:
            continue
        res = handle(cmd)
        res["finished_at"] = time.time()
        try:
            atomic_write(os.path.join(OUTBOX, n), res)
            os.remove(p)
            if res.get("ok"):
                done += 1
            else:
                failed += 1
        except Exception:
            failed += 1
    heartbeat()
    print("[sfm_bridge] batch done: %d ok, %d failed. Submit again for next batch." % (done, failed))
    return done, failed


if __name__ == "__main__":
    # Single batch per Submit: processes the whole queue in seconds,
    # then returns control. No loops, no threads, no sleeps.
    poll_once()
