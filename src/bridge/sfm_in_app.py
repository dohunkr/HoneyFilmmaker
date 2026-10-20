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
    Order: sfm.GetCurrentShot() -> sfmApp.GetShots()[0] -> sfmApp.GetShots()[name]."""
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
        shots = sfmApp.GetShots()
    except Exception as e:
        return None, "sfmApp.GetShots failed: %s" % e
    if not shots:
        return None, "no shots in document"
    if name:
        for s in shots:
            try:
                if str(s.name) == str(name):
                    return s, "sfmApp.GetShots[name=%s]" % name
            except Exception:
                continue
    return shots[0], "sfmApp.GetShots[0]"


def sfm_model_path_candidates(asset_path):
    """SFM accepts different relative forms depending on how the model was
    registered. Try them in order and use the first that loads."""
    raw = str(asset_path).replace("\\", "/").strip()
    cands = [raw]
    if raw.lower().startswith("tf/"):
        cands.append(raw[3:])
    if not raw.lower().startswith("tf/") and not raw.lower().startswith("models/"):
        cands.append("tf/" + raw)
    if not raw.lower().startswith("models/"):
        cands.append("models/" + raw.split("/")[-2] + "/" + raw.split("/")[-1]
                     if "/" in raw else raw)
    # absolute form
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


def sfm_diagnose():
    """Collect everything the MCP side needs to debug SFM access.
    Written to a file so the operator only has to press Submit once."""
    import traceback
    rep = {"ts": time.time(), "have_sfm": HAVE_SFM}
    try:
        import sfm
        rep["sfm_model_fns"] = [x for x in dir(sfm)
                                if "odel" in x or "List" in x or "Path" in x]
        rep["sfm_fns_all"] = [x for x in dir(sfm) if not x.startswith("_")]
    except Exception:
        rep["sfm_import_error"] = traceback.format_exc(limit=2)
    try:
        import sfmApp
        rep["sfmApp_fns"] = [x for x in dir(sfmApp) if not x.startswith("_")]
        try:
            rep["has_document"] = bool(sfmApp.HasDocument())
        except Exception:
            rep["has_document"] = None
        try:
            shots = sfmApp.GetShots()
            rep["shots"] = [str(getattr(s, "name", "?")) for s in shots]
        except Exception:
            rep["shots_error"] = traceback.format_exc(limit=2)
    except Exception:
        rep["sfmApp_import_error"] = traceback.format_exc(limit=2)
    # model load attempts
    tries = []
    paths = [
        "models/player/scout.mdl", "tf/models/player/scout.mdl",
        "models/player/soldier.mdl",
        "models/bots/soldier/bot_soldier.mdl",
        "models/player/hwm/scout.mdl",
    ]
    for gd in [r"D:\SteamLibrary\steamapps\common\SourceFilmmaker\game",
               r"D:\SteamLibrary\steamapps\common\SourceFilmmaker\game\tf"]:
        for p in ["models/player/scout.mdl", "player/scout.mdl", "scout.mdl"]:
            paths.append(gd.replace("\\", "/") + "/" + p)
    try:
        import sfm
        for p in paths:
            try:
                m = sfm.CreateModel(p)
                tries.append({"path": p, "result": "OK" if m is not None else "None"})
                if m is not None:
                    break
            except Exception as e:
                tries.append({"path": p, "error": str(e)[:120]})
    except Exception:
        pass
    rep["create_model_tries"] = tries
    out = os.path.join(QUEUE, "diagnose.json")
    try:
        with open(out, "w") as f:
            json.dump(rep, f, indent=2)
        rep["written"] = out
    except Exception:
        rep["write_error"] = traceback.format_exc(limit=2)
    print("[sfm_bridge] diagnose written to %s" % out)
    return rep


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
    return {"ok": True, "name": name, "path": used, "shot": how,
            "animSet": bool(animSet is not None), "moved": moved}


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
