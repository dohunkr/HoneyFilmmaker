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


def sfm_place_model(name, asset_path, pos=None):
    """Real placement via Valve's sfmUtils pattern. Returns dict result."""
    try:
        import sfm
    except Exception:
        return {"ok": False, "error": "no sfm module (run inside SFM)"}
    try:
        import vs
    except Exception:
        return {"ok": False, "error": "no vs module (run inside SFM)"}
    try:
        shot = sfm.GetCurrentShot()
    except Exception as e:
        return {"ok": False, "error": "GetCurrentShot failed: %s" % e}
    if shot is None:
        return {"ok": False, "code": "NO_CURRENT_SHOT",
                "error": "no current shot",
                "hint": "Double-click shot1 in the timeline, then retry"}
    path = str(asset_path).replace("\\", "/")
    try:
        model = sfm.CreateModel(path)
    except Exception as e:
        return {"ok": False, "error": "CreateModel raised: %s" % e}
    if model is None:
        return {"ok": False, "error": "CreateModel returned None for %s" % path,
                "hint": "Check the .mdl exists under game/ (use search_assets)"}
    try:
        animSet = sfm.CreateAnimationSet(str(name), target=model)
    except Exception as e:
        return {"ok": False, "error": "CreateAnimationSet raised: %s" % e,
                "note": "model object was created"}
    try:
        dag = vs.CreateElement("DmeDag", str(name), shot.GetFileId())
        dag.AddChild(model)
        shot.scene.AddChild(dag)
    except Exception as e:
        return {"ok": False, "error": "dag attach raised: %s" % e,
                "note": "model+animSet exist"}
    moved = None
    if pos is not None:
        try:
            sfm.SelectDag(dag)
            sfm.Move(float(pos[0]), float(pos[1]), float(pos[2]))
            moved = list(pos)
        except Exception as e:
            moved = "Move failed: %s (placed at origin)" % e
    return {"ok": True, "name": name, "path": path,
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
                                params.get("pos"))
            r["id"] = cmd.get("id")
            r["session"] = info
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
