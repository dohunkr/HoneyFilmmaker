# -*- coding: utf-8 -*-
# HoneyFilmmaker SFM bridge - installed as usermod/scripts/sfm/sfm_init.py
# Runs automatically when SFM starts (main window focused).
#
# Why this file exists: the 'sfm' module is only fully functional when the
# script runs inside SFM's own startup context. A snippet pasted into the
# Script Editor imports 'sfm' but CreateModel() always returns None there.
# This startup script has the real context, so model placement works.
#
# It also autosaves the session so a crash never loses work again.
import os
import sys
import json
import time
import traceback
import re

try:
    from PySide import QtCore
    from PySide import QtGui
    from PySide import shiboken
    HAVE_QT = True
except Exception:
    HAVE_QT = False

try:
    import sfmApp
    HAVE_APP = True
except Exception:
    HAVE_APP = False

try:
    import sfm
    HAVE_SFM = True
except Exception:
    HAVE_SFM = False

try:
    import vs
    HAVE_VS = True
except Exception:
    HAVE_VS = False


WORKDIR = os.environ.get("HONEY_WORKDIR", r"D:\Github\HoneyFilmmaker\workdir")
QUEUE = os.path.join(WORKDIR, "bridge_queue")
INBOX = os.path.join(QUEUE, "inbox")
OUTBOX = os.path.join(QUEUE, "outbox")
HEARTBEAT = os.path.join(QUEUE, "heartbeat.json")
SESSION = os.path.join(QUEUE, "last_session.json")
DIAG = os.path.join(QUEUE, "diagnose.json")
AUTOSAVE_DIR = os.path.join(WORKDIR, "autosaves")

# Tracks whether a document is open, so we can re-diagnose when it changes.
_last_doc_state = None


def log(msg):
    try:
        print "[honey] %s" % msg
    except Exception:
        try:
            print msg
        except Exception:
            pass


def ensure_dirs():
    for d in (QUEUE, INBOX, OUTBOX, AUTOSAVE_DIR):
        if not os.path.isdir(d):
            try:
                os.makedirs(d)
            except Exception:
                pass


def atomic_write(path, data):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
        os.rename(tmp, path)
        return True
    except Exception:
        return False


def heartbeat():
    atomic_write(HEARTBEAT, {"ts": time.time(), "have_sfm": HAVE_SFM,
                              "have_vs": HAVE_VS, "have_qt": HAVE_QT,
                              "pid": os.getpid()})


# ---------------------------------------------------------------- models
def path_candidates():
    """Model paths SFM actually accepts.
    tf/gameinfo.txt SearchPaths:
        Game |gameinfo_path| .   -> tf/models/...
        Game tf                  -> tf/tf/models/...
        |all_source_engine_paths|hl2 -> hl2/models/...
    So the virtual path for TF2 content is models/player/hwm/<class>.mdl
    and hl2/models/... for HL2 content."""
    gd = "D:/SteamLibrary/steamapps/common/SourceFilmmaker/game"
    rels = ["models/player/hwm/scout.mdl", "models/player/hwm/soldier.mdl",
            "models/player/hwm/spy.mdl",
            "models/bots/soldier_boss/bot_soldier_boss.mdl",
            "models/bots/soldier/bot_soldier.mdl",
            "models/props_c17/oildrum001.mdl",
            "models/props_lab/consolebox01a.mdl",
            "models/props_phx/construct/metal_doorbell_button.mdl"]
    out = []
    for r in rels:
        out.append(r)
        out.append("tf/" + r)
        out.append(gd + "/" + r)
        out.append(gd + "/tf/" + r)
        out.append(gd + "/tf/tf/" + r)
    seen = set()
    res = []
    for c in out:
        if c not in seen:
            seen.add(c)
            res.append(c)
    return res


def find_shot(name=None):
    if HAVE_SFM:
        try:
            s = sfm.GetCurrentShot()
            if s is not None:
                return s, "sfm.GetCurrentShot"
        except Exception:
            pass
    if not HAVE_APP:
        return None, "no sfmApp"
    try:
        if not sfmApp.HasDocument():
            return None, "no document"
    except Exception:
        pass
    try:
        s = sfmApp.GetShotAtCurrentTime()
        if s is not None:
            return s, "GetShotAtCurrentTime"
    except Exception:
        pass
    try:
        shots = sfmApp.GetShots()
    except Exception:
        return None, "GetShots failed"
    if not shots:
        return None, "no shots"
    if name:
        for s in shots:
            try:
                if str(s.GetName()) == str(name):
                    return s, "GetShots[name]"
            except Exception:
                pass
    return shots[0], "GetShots[0]"


def place_model(name, model_path, pos=None, shot_name=None):
    if not (HAVE_SFM and HAVE_VS):
        return {"ok": False, "error": "sfm/vs modules unavailable in this context"}
    shot, how = find_shot(shot_name)
    if shot is None:
        return {"ok": False, "code": "NO_SHOT", "error": "no shot (%s)" % how}
    cands = path_candidates()
    # allow explicit override first
    ordered = []
    if model_path:
        ordered.append(model_path)
    for c in cands:
        if c not in ordered:
            ordered.append(c)
    model = None
    used = None
    tried = []
    for c in ordered:
        try:
            m = sfm.CreateModel(c)
        except Exception as e:
            tried.append("%s -> ERR %s" % (c, str(e)[:70]))
            continue
        tried.append("%s -> %s" % (c, "OK" if m is not None else "None"))
        if m is not None:
            model = m
            used = c
            break
    if model is None:
        return {"ok": False, "error": "CreateModel failed for all paths",
                "tried": tried[:20]}
    animset = None
    try:
        animset = sfm.CreateAnimationSet(str(name), target=model)
    except Exception as e:
        return {"ok": False, "error": "CreateAnimationSet: %s" % e, "path_used": used}
    try:
        dag = vs.CreateElement("DmeDag", str(name), shot.GetFileId())
        dag.AddChild(model)
        shot.scene.AddChild(dag)
    except Exception as e:
        return {"ok": False, "error": "dag attach: %s" % e, "path_used": used}
    moved = None
    if pos is not None:
        try:
            sfm.SelectDag(dag)
            sfm.Move(float(pos[0]), float(pos[1]), float(pos[2]))
            moved = [float(pos[0]), float(pos[1]), float(pos[2])]
        except Exception as e:
            moved = "Move failed: %s" % e
    return {"ok": True, "name": name, "path": used, "shot": how,
            "animset": animset is not None, "moved": moved, "tried": tried[:8]}


def set_transform(name, pos=None, rot=None):
    if not HAVE_SFM:
        return {"ok": False, "error": "no sfm module"}
    try:
        dag = sfm.FindDag(str(name))
    except Exception as e:
        return {"ok": False, "error": "FindDag: %s" % e}
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


def save_session(tag=""):
    if not HAVE_APP:
        return {"ok": False, "error": "no sfmApp"}
    try:
        if not sfmApp.HasDocument():
            return {"ok": False, "error": "no document open"}
    except Exception:
        return {"ok": False, "error": "HasDocument failed"}
    try:
        name = str(sfmApp.GetMovie().name)
    except Exception:
        name = "session"
    safe = re.sub(r'[\/:*?"<>|]', '', name)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = "usermod/elements/sessions/autosaves/%s-%s.dmx" % (safe, stamp)
    try:
        sfmApp.SaveDocument(target)
        return {"ok": True, "saved": target}
    except Exception as e:
        try:
            sfmApp.SaveDocument()
            return {"ok": True, "saved": "current"}
        except Exception as e2:
            return {"ok": False, "error": "SaveDocument: %s / %s" % (e, e2)}


def list_objects():
    if not HAVE_APP:
        return {"ok": False, "error": "no sfmApp"}
    out = []
    try:
        shots = sfmApp.GetShots()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    for s in shots:
        entry = {"shot": str(s.GetName()), "objects": []}
        try:
            scene = s.scene
            for child in scene.children:
                try:
                    entry["objects"].append(str(child.GetName()))
                except Exception:
                    pass
        except Exception:
            pass
        out.append(entry)
    return {"ok": True, "shots": out}


def diagnose():
    rep = {"ts": time.time(), "have_sfm": HAVE_SFM, "have_vs": HAVE_VS,
           "have_qt": HAVE_QT, "have_app": HAVE_APP, "pid": os.getpid(),
           "modules": [m for m in ["sfm", "vs", "sfmApp", "dm"]
                       if m in sys.modules]}
    shot, how = find_shot()
    rep["shot_source"] = how
    rep["shot_name"] = None if shot is None else str(shot.GetName())
    try:
        rep["timeline_mode"] = str(sfmApp.GetTimelineMode())
    except Exception:
        pass
    # real model load test
    tries = []
    model = None
    used = None
    for c in path_candidates():
        try:
            m = sfm.CreateModel(c)
        except Exception as e:
            tries.append("%s -> ERR %s" % (c, str(e)[:70]))
            continue
        tries.append("%s -> %s" % (c, "OK" if m is not None else "None"))
        if m is not None:
            model = m
            used = c
            break
    rep["create_model_tried"] = tries
    rep["create_model_winner"] = used
    if model is not None and shot is not None:
        try:
            a = sfm.CreateAnimationSet("DIAG_PROBE", target=model)
            rep["animset"] = a is not None
            d = vs.CreateElement("DmeDag", "DIAG_PROBE", shot.GetFileId())
            d.AddChild(model)
            shot.scene.AddChild(d)
            rep["attached"] = True
        except Exception as e:
            rep["attach_error"] = str(e)[:150]
    atomic_write(DIAG, rep)
    log("diagnose written")
    return rep


def handle(cmd):
    name = cmd.get("command")
    params = cmd.get("params", {})
    if name == "ping":
        return {"ok": True, "result": {"have_sfm": HAVE_SFM, "have_vs": HAVE_VS}}
    if name == "get_session":
        shot, how = find_shot()
        return {"ok": True, "result": {"shot": how, "shot_name":
                                       None if shot is None else str(shot.GetName())}}
    if name == "add_model":
        r = place_model(params.get("name", "model"),
                        params.get("asset_path", ""),
                        params.get("pos"), params.get("shot"))
        r["saved"] = save_session()
        return r
    if name == "set_transform":
        return set_transform(params.get("name", ""), params.get("pos"),
                             params.get("rot"))
    if name == "list_objects":
        return list_objects()
    if name == "diagnose":
        r = diagnose()
        r["ok"] = True
        return r
    if name == "save":
        return save_session()
    if name == "create_scene":
        return {"ok": False, "code": "NO_API",
                "error": "create_scene has no verified SFM API",
                "hint": "load the map in the UI, or use sfmApp.LoadMap"}
    return {"ok": False, "error": "unknown command: %s" % name}


def poll_once():
    ensure_dirs()
    heartbeat()
    done = 0
    failed = 0
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
        try:
            res = handle(cmd)
        except Exception:
            res = {"ok": False, "error": traceback.format_exc(limit=3)}
        res["id"] = cmd.get("id")
        res["finished_at"] = time.time()
        # A command that failed only because no document was open is retried
        # later, when the operator opens a session.
        retryable = (not res.get("ok")) and (
            res.get("code") == "NO_SHOT" or "no document" in str(res.get("error", ""))
            or "no shot" in str(res.get("error", "")))
        if retryable:
            # keep it in the inbox for the next poll
            try:
                res["retry_pending"] = True
                atomic_write(os.path.join(OUTBOX, n + ".pending"), res)
            except Exception:
                pass
            continue
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
    log("batch done: %d ok, %d failed" % (done, failed))
    return done, failed


def _refresh_diagnose_if_needed():
    """Re-run diagnosis when the document state changes (session opened)."""
    global _last_doc_state
    try:
        has = bool(sfmApp.HasDocument())
    except Exception:
        has = False
    if has == _last_doc_state:
        return
    _last_doc_state = has
    log("document state changed -> %s, re-diagnosing" % has)
    try:
        diagnose()
    except Exception:
        pass


# ---------------------------------------------------------------- autosave
def start_autosave(interval_sec=300):
    if not (HAVE_APP and HAVE_QT):
        return False

    def _tick():
        try:
            if not sfmApp.HasDocument():
                return
            name = str(sfmApp.GetMovie().name)
        except Exception:
            return
        safe = re.sub(r'[\/:*?"<>|]', '', name)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        target = "usermod/elements/sessions/autosaves/%s-%s.dmx" % (safe, stamp)
        try:
            sfmApp.SaveDocument(target)
            log("autosaved %s" % target)
        except Exception as e:
            log("autosave failed: %s" % e)

    try:
        timer = QtCore.QTimer()
        timer.timeout.connect(_tick)
        timer.start(interval_sec * 1000)
        QtCore.QCoreApplication.instance().aboutToQuit.connect(
            lambda: shiboken.delete(timer))
        log("autosave every %ss" % interval_sec)
        return True
    except Exception as e:
        log("autosave timer failed: %s" % e)
        return False


# ---------------------------------------------------------------- bootstrap
def _delayed_start():
    """Run the real work. Must never raise out of here: a crash here kills
    the whole bridge silently, so everything is wrapped and logged to disk."""
    try:
        ensure_dirs()
        heartbeat()
        log("=== HoneyFilmmaker bridge start (delayed) ===")
        log("sfm=%s vs=%s sfmApp=%s qt=%s" % (HAVE_SFM, HAVE_VS, HAVE_APP, HAVE_QT))
        try:
            diagnose()
        except Exception:
            log("diagnose failed: %s" % traceback.format_exc(limit=2))
        try:
            poll_once()
        except Exception:
            log("poll failed: %s" % traceback.format_exc(limit=2))
        if HAVE_QT:
            try:
                poll_timer = QtCore.QTimer()
                poll_timer.timeout.connect(poll_once)
                poll_timer.start(2000)
                globals()["_poll_timer"] = poll_timer
                start_autosave(300)
                log("poll timer 2s active")
            except Exception as e:
                log("poll timer failed: %s" % e)
    except Exception:
        try:
            with open(os.path.join(QUEUE, "startup_error.txt"), "w") as f:
                f.write(traceback.format_exc())
        except Exception:
            pass
        log("delayed start error: %s" % traceback.format_exc(limit=3))


def _loop_worker():
    """Background poll loop that does not depend on Qt at all."""
    while True:
        try:
            poll_once()
        except Exception:
            pass
        time.sleep(2)


def bootstrap():
    ensure_dirs()
    log("USERMOD: Python initial startup complete")
    log("HoneyFilmmaker: sfm_init loaded (sfm=%s vs=%s qt=%s)"
        % (HAVE_SFM, HAVE_VS, HAVE_QT))
    heartbeat()
    if HAVE_QT:
        try:
            QtCore.QTimer.singleShot(3000, _delayed_start)
            log("delayed start scheduled in 3s")
        except Exception as e:
            log("singleShot failed: %s" % e)
            _delayed_start()
    else:
        _delayed_start()


# Run the poll loop on a plain thread: it never depends on the Qt event loop
# being alive. Also runs the one-shot diagnosis first.
def _thread_worker():
    import threading

    def _run():
        try:
            _delayed_start()
        except Exception:
            pass
        while True:
            try:
                _refresh_diagnose_if_needed()
                poll_once()
            except Exception:
                pass
            time.sleep(2)

    try:
        t = threading.Thread(target=_run)
        t.daemon = True
        t.start()
        log("poll thread started")
    except Exception as e:
        log("thread failed: %s" % e)


try:
    bootstrap()
except Exception:
    log("bootstrap error: %s" % traceback.format_exc(limit=3))

# Always start the thread worker: it is the reliable path.
_thread_worker()
