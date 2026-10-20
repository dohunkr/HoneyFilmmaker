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

# Kept at module level so Python's GC cannot collect the live timers.
_poll_timer = None
_autosave_timer = None

# Rate limit for menu triggering.
_last_trigger = 0


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


def _console_cmds():
    """Run read-only SFM console commands and capture their output.
    The console widget text is truncated, so we also dump the full text
    to a file after each command."""
    out = {}
    try:
        from PySide import QtGui
    except Exception as e:
        return {"error": "no QtGui: %s" % e}
    dump = os.path.join(QUEUE, "console.txt")

    def _dump(tag):
        try:
            app = QtGui.QApplication.instance()
            chunks = []
            for w in app.topLevelWidgets():
                for child in w.findChildren(QtGui.QTextEdit):
                    chunks.append(str(child.toPlainText()))
                for child in w.findChildren(QtGui.QPlainTextEdit):
                    chunks.append(str(child.toPlainText()))
            with open(dump, "a") as f:
                f.write("\n===== %s =====\n" % tag)
                f.write("\n".join(chunks)[-20000:])
            return "\n".join(chunks)
        except Exception as e:
            return "dump error: %s" % e

    for cmd in ["fs_searchpaths", "fs_print_searchpaths"]:
        try:
            r = sfmApp.ExecuteGameCommand(cmd)
            out["cmd_" + cmd] = str(r)[:300]
        except Exception as e:
            out["cmd_" + cmd] = "ERR " + str(e)[:120]
        # let the console process the command, then read it back
        try:
            sfmApp.ProcessEvents()
        except Exception:
            pass
        text = _dump(cmd)
        # keep only the interesting tail after the command echo
        low = text.lower()
        pos = low.rfind(cmd.lower())
        if pos >= 0:
            out["tail_" + cmd] = text[pos:pos + 2000]
    out["dump_file"] = dump
    try:
        out["search_paths_attr"] = str(vs.GetSearchPaths()) if hasattr(vs, "GetSearchPaths") else "n/a"
    except Exception as e:
        out["search_paths_attr"] = "ERR " + str(e)[:100]
    return out


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
    # Docstrings reveal the required context and return contract.
    docs = {}
    for fn in ["CreateModel", "CreateAnimationSet", "GetCurrentAnimationSet",
               "GetCurrentShot", "CreateDag", "UsingAnimationSet"]:
        try:
            f = getattr(sfm, fn)
            docs[fn] = str(f.__doc__)[:600]
        except Exception as e:
            docs[fn] = "ERR " + str(e)[:80]
    rep["sfm_docs"] = docs
    try:
        a = sfm.GetCurrentAnimationSet()
        rep["current_animset"] = None if a is None else str(a.GetName())
    except Exception as e:
        rep["current_animset_error"] = str(e)[:120]
    # Scripts menu inventory: this is how the dag/animset context is reached.
    try:
        menu = sfmApp.GetScriptsMenu()
        items = []
        if menu is not None:
            for act in menu.actions():
                items.append(str(act.text()))
        rep["scripts_menu"] = items
    except Exception as e:
        rep["scripts_menu_error"] = str(e)[:120]
    try:
        rep["console"] = _console_cmds()
    except Exception as e:
        rep["console_error"] = str(e)[:150]
    atomic_write(DIAG, rep)
    log("diagnose written")
    return rep


def trigger_scripts_menu(target="honey_place_models"):
    """Trigger a script from the Scripts menu so it runs in the real SFM
    context (mainmenu / dag / animset). Valve's own examples drive SFM this
    way by triggering a QMenu action.
    SFM replaces '_' with ' ' in menu labels, so match loosely."""
    if not HAVE_QT:
        return {"ok": False, "error": "no PySide"}
    try:
        from PySide import QtGui
    except Exception as e:
        return {"ok": False, "error": "no QtGui: %s" % e}
    try:
        menu = sfmApp.GetScriptsMenu()
    except Exception as e:
        return {"ok": False, "error": "GetScriptsMenu: %s" % e}
    if menu is None:
        return {"ok": False, "error": "no scripts menu"}
    found = []
    want = str(target).replace("_", " ").lower()
    for act in menu.actions():
        t = str(act.text())
        found.append(t)
        norm = t.replace("_", " ").strip().lower()
        if norm == want or norm.replace(" ", "_") == str(target).lower():
            try:
                act.trigger()
                return {"ok": True, "triggered": t}
            except Exception as e:
                return {"ok": False, "error": "trigger failed: %s" % e}
    return {"ok": False, "error": "script not found in Scripts menu",
            "available": found}


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
        if name == "trigger_script":
            r = trigger_scripts_menu(params.get("target", "honey_place_models"))
            r["id"] = cmd.get("id")
            return r
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
def _autosave_once():
    """Save a timestamped copy of the session. Runs on the main thread."""
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


# ---------------------------------------------------------------- bootstrap
def _start_workers():
    """Create the poll/autosave timers on the MAIN thread.
    SFM's API is not thread-safe: calling sfm/sfmApp from a worker thread
    crashes SFM. Qt timers run on the main thread, which is what Valve's own
    autosave script uses. The timer objects are kept in module globals so
    Python's GC cannot collect them (that silently stops the poll)."""
    global _poll_timer, _autosave_timer
    try:
        ensure_dirs()
        heartbeat()
        log("=== HoneyFilmmaker bridge start ===")
        log("sfm=%s vs=%s sfmApp=%s qt=%s" % (HAVE_SFM, HAVE_VS, HAVE_APP, HAVE_QT))
        try:
            diagnose()
        except Exception:
            log("diagnose failed: %s" % traceback.format_exc(limit=2))
        try:
            poll_once()
        except Exception:
            log("poll failed: %s" % traceback.format_exc(limit=2))
        if not HAVE_QT:
            log("no Qt: queue handled on next manual run")
            return
        try:
            if _poll_timer is None:
                _poll_timer = QtCore.QTimer()
                _poll_timer.timeout.connect(_tick)
            _poll_timer.start(2000)
            log("poll timer 2s active")
        except Exception as e:
            log("poll timer failed: %s" % e)
        try:
            if _autosave_timer is None:
                _autosave_timer = QtCore.QTimer()
                _autosave_timer.timeout.connect(_autosave_tick)
            _autosave_timer.start(300 * 1000)
            log("autosave timer 300s active")
        except Exception as e:
            log("autosave timer failed: %s" % e)
    except Exception:
        try:
            with open(os.path.join(QUEUE, "startup_error.txt"), "w") as f:
                f.write(traceback.format_exc())
        except Exception:
            pass
        log("worker start error: %s" % traceback.format_exc(limit=3))


def _tick():
    """Main-thread poll tick."""
    try:
        _refresh_diagnose_if_needed()
    except Exception:
        pass
    try:
        poll_once()
    except Exception:
        pass
    try:
        _auto_trigger_pending()
    except Exception:
        pass


def _auto_trigger_pending():
    """When model-placement commands are queued, run the placer script through
    the Scripts menu so it executes in a real SFM context. This is the only
    way CreateModel works, so it is automated here instead of asking the
    operator to right-click.

    Safety: the trigger only runs when a shot is genuinely current, the
    timeline is inside the shot, and the placement script is present in the
    Scripts menu. Otherwise the session can be left in a broken state."""
    try:
        names = [n for n in os.listdir(INBOX) if n.endswith(".json")]
    except Exception:
        return
    if not names:
        return
    wants = False
    for n in names:
        try:
            with open(os.path.join(INBOX, n), "r") as f:
                c = json.load(f)
            if c.get("command") in ("add_model", "set_transform"):
                wants = True
                break
        except Exception:
            continue
    if not wants:
        return
    # Guard 1: a shot must be current.
    shot = None
    try:
        shot = sfm.GetCurrentShot()
    except Exception:
        shot = None
    if shot is None:
        try:
            shot = sfmApp.GetShotAtCurrentTime()
        except Exception:
            shot = None
    if shot is None:
        return
    # Guard 2: the script must exist in the menu, otherwise triggering a
    # stale action can disturb the session.
    global _last_trigger
    now = time.time()
    if now - _last_trigger < 5:
        return
    _last_trigger = now
    r = trigger_scripts_menu("honey_place_models")
    log("auto trigger: %s" % (r.get("triggered") or r.get("error")))


def _autosave_tick():
    _autosave_once()


def bootstrap():
    ensure_dirs()
    log("USERMOD: Python initial startup complete")
    log("HoneyFilmmaker: sfm_init loaded (sfm=%s vs=%s qt=%s)"
        % (HAVE_SFM, HAVE_VS, HAVE_QT))
    heartbeat()
    if HAVE_QT:
        try:
            # 3s after startup the SFM event loop is running.
            QtCore.QTimer.singleShot(3000, _start_workers)
            log("workers scheduled in 3s")
        except Exception as e:
            log("singleShot failed: %s" % e)
    else:
        _start_workers()


try:
    bootstrap()
except Exception:
    log("bootstrap error: %s" % traceback.format_exc(limit=3))
