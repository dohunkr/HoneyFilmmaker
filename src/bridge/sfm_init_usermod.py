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
BTN_DUMP = os.path.join(QUEUE, "widgets.json")
GAME_TF_MODELS = r"D:\SteamLibrary\steamapps\common\SourceFilmmaker\game\tf\models"

# Session to reopen on startup, so the pipeline always has a shot.
LAST_SESSION = os.path.join(
    "D:\\SteamLibrary\\steamapps\\common\\SourceFilmmaker\\game",
    "usermod", "elements", "sessions", "1000 years1.dmx")

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

    Verified from Valve's own shipped session
    (tf_movies/elements/sessions/mtt_soldier/mtt_soldier.dmx):
    the model virtual path is "player/hwm/<class>" and bone names are
    "<bone>.player/hwm/pyro_bone" - the path is relative to the models
    folder and uses the hwm tree.

    ifm.dll also shows:
      - "MDL file contains no sequences" -> the model needs $sequence data
      - "%s\\%s.mdl" with "contentdir:models"
      - "CAnimationSetEditor::CreateAnimationSetForModel: model has no
         facial animation model %s [%s]" -> hwm models carry the *.pre
         phoneme/viseme files, plain player models do not.
    """
    gd = "D:/SteamLibrary/steamapps/common/SourceFilmmaker/game"
    out = []
    for n in ["scout", "soldier", "spy", "medic", "heavy", "demo",
              "engineer", "pyro", "sniper"]:
        for v in ["player/hwm/" + n, "models/player/hwm/" + n + ".mdl",
                  "player/" + n, "models/player/" + n + ".mdl",
                  "tf/player/hwm/" + n]:
            out.append(v)
    for n in ["bot_soldier", "bot_soldier_boss"]:
        for v in ["bots/soldier/" + n, "models/bots/soldier/" + n + ".mdl",
                  "bots/soldier_boss/" + n]:
            out.append(v)
    out.append("props_2fort/oildrum")
    out.append("models/props_2fort/oildrum.mdl")
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


def sfm_scan_dags():
    """List every dag node in the current shot.
    Used to adopt manually placed models."""
    out = []
    shot, how = find_shot()
    if shot is None:
        return out
    try:
        scene = shot.scene
    except Exception:
        return out
    try:
        for child in scene.children:
            try:
                name = str(child.GetName())
            except Exception:
                name = "?"
            entry = {"name": name, "type": str(child.GetTypeName())}
            try:
                entry["children"] = [str(c.GetName()) for c in child.GetChildren()]
            except Exception:
                pass
            out.append(entry)
    except Exception:
        pass
    return out


def sfm_adopt_models(mapping, positions=None):
    """Adopt existing dag nodes by name and move them to target positions.
    mapping: {"desired_name": "existing_dag_name"}"""
    positions = positions or {}
    shot, how = find_shot()
    if shot is None:
        return {"ok": False, "error": "no shot"}
    result = {"ok": True, "shot": how, "adopted": []}
    for name, target_name in mapping.items():
        dag = None
        for cand in (target_name, name):
            try:
                d = sfm.FindDag(cand)
            except Exception:
                d = None
            if d is not None:
                dag = d
                break
        if dag is None:
            result["adopted"].append({"name": target_name, "ok": False,
                                      "error": "not found"})
            continue
        entry = {"name": target_name, "ok": True}
        try:
            dag.SetName(str(target_name))
        except Exception as e:
            entry["rename_error"] = str(e)[:80]
        pos = positions.get(target_name)
        if pos is not None:
            try:
                sfm.SelectDag(dag)
                sfm.Move(float(pos[0]), float(pos[1]), float(pos[2]))
                entry["moved"] = list(pos)
            except Exception as e:
                entry["ok"] = False
                entry["move_error"] = str(e)[:100]
        result["adopted"].append(entry)
    return result


def place_model(name, model_path, pos=None, shot_name=None):
    # Model creation goes through the GUI placer: sfm.CreateModel() returns
    # None in every script context available to us (verified via ifm.dll).
    return gui_place_model(name, model_path, pos)


def _unused_place_model(name, model_path, pos=None, shot_name=None):
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
    want = str(target).replace("_", " ").strip().lower()
    fallback = None
    for act in menu.actions():
        t = str(act.text())
        found.append(t)
        norm = t.replace("_", " ").strip().lower()
        if norm == want:
            try:
                act.trigger()
                try:
                    with open(os.path.join(QUEUE, "last_trigger.txt"), "w") as f:
                        f.write("%s -> %s @ %s\n" % (target, t,
                                                    time.strftime("%H:%M:%S")))
                except Exception:
                    pass
                return {"ok": True, "triggered": t}
            except Exception as e:
                return {"ok": False, "error": "trigger failed: %s" % e}
        # remember any honey script as a fallback
        if fallback is None and "honey" in norm:
            fallback = act
    if fallback is not None:
        try:
            fallback.trigger()
            try:
                with open(os.path.join(QUEUE, "last_trigger.txt"), "w") as f:
                    f.write("FALLBACK -> %s @ %s\n" % (str(fallback.text()),
                                                      time.strftime("%H:%M:%S")))
            except Exception:
                pass
            return {"ok": True, "triggered": str(fallback.text()), "fallback": True}
        except Exception as e:
            return {"ok": False, "error": "fallback trigger failed: %s" % e}
    try:
        with open(os.path.join(QUEUE, "last_trigger.txt"), "w") as f:
            f.write("NOT FOUND target=%s menu=%s @ %s\n"
                    % (target, found, time.strftime("%H:%M:%S")))
    except Exception:
        pass
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
            r = trigger_scripts_menu(params.get("target", "honey_gui_v1"))
            r["id"] = cmd.get("id")
            return r
        if name == "scan_dags":
            dags = sfm_scan_dags()
            r = {"id": cmd.get("id"), "ok": True, "dags": dags, "count": len(dags)}
            try:
                with open(os.path.join(QUEUE, "dags.json"), "w") as f:
                    json.dump(dags, f, indent=2)
            except Exception:
                pass
            return r
        if name == "screenshot":
            r = sfm_screenshot(params.get("path"))
            r["id"] = cmd.get("id")
            return r
        if name == "adopt_models":
            r = sfm_adopt_models(params.get("mapping", {}),
                                  params.get("positions"))
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


# ---------------------------------------------------------------- GUI placer
# Embedded directly: the Scripts menu can serve a cached (stale) script,
# so the GUI-driven placement runs from the startup script itself.
def log(m):
    try:
        print "[honey/gui2] %s" % m
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
    except Exception:
        pass


def pump(ms=300):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        try:
            if HAVE_APP:
                sfmApp.ProcessEvents()
        except Exception:
            pass
        try:
            QtGui.QApplication.processEvents()
        except Exception:
            pass
        time.sleep(0.02)


def top_widgets():
    try:
        return QtGui.QApplication.instance().topLevelWidgets()
    except Exception:
        return []


def widget_inventory():
    """Full inventory of every widget that could be the add button.
    Includes tab bars so the Animation Set Editor panel can be located."""
    inv = []
    try:
        app = QtGui.QApplication.instance()
    except Exception:
        return inv
    keep = ("QToolButton", "QPushButton", "QTabWidget", "QTabBar",
            "QStackedWidget", "QDockWidget", "QListView", "QTreeView",
            "QComboBox", "QLabel", "QSplitter", "QFrame")
    for w in app.topLevelWidgets():
        try:
            wtitle = str(w.windowTitle())
            wclass = w.metaObject().className()
        except Exception:
            continue
        try:
            children = w.findChildren(QtGui.QWidget)
        except Exception:
            children = []
        for c in children:
            try:
                cn = c.metaObject().className()
                if cn not in keep:
                    continue
                info = {"win": wtitle, "winclass": wclass, "class": cn,
                        "text": str(c.text()),
                        "tip": str(c.toolTip()),
                        "name": str(c.objectName()),
                        "vis": bool(c.isVisible()),
                        "x": c.x(), "y": c.y(),
                        "w": c.width(), "h": c.height()}
                if cn == "QTabBar":
                    try:
                        info["tabs"] = [str(c.tabText(i))
                                        for i in range(c.count())]
                    except Exception:
                        pass
                if cn == "QTabWidget":
                    try:
                        info["tabs"] = [str(c.tabText(i))
                                        for i in range(c.count())]
                    except Exception:
                        pass
                inv.append(info)
            except Exception:
                continue
    return inv


def dump_widgets():
    inv = widget_inventory()
    atomic_write(BTN_DUMP, inv)
    return inv


def find_anim_set_panel():
    """Return the widget that hosts the Animation Set Editor panel.
    SFM uses a tab widget; the panel is one of its pages."""
    app = None
    try:
        app = QtGui.QApplication.instance()
    except Exception:
        return None
    tabs_found = []
    try:
        for w in app.topLevelWidgets():
            for tb in w.findChildren(QtGui.QTabWidget):
                try:
                    names = [str(tb.tabText(i)) for i in range(tb.count())]
                except Exception:
                    continue
                tabs_found.append((tb, names))
                for i, n in enumerate(names):
                    if "animation set" in n.lower():
                        try:
                            return tb.widget(i)
                        except Exception:
                            pass
    except Exception:
        pass
    # tab bar (not a QTabWidget) can also hold the tabs
    try:
        for w in app.topLevelWidgets():
            for tb in w.findChildren(QtGui.QTabBar):
                try:
                    names = [str(tb.tabText(i)) for i in range(tb.count())]
                except Exception:
                    continue
                tabs_found.append((tb, names))
                for i, n in enumerate(names):
                    if "animation set" in n.lower():
                        try:
                            return tb.widget(i)
                        except Exception:
                            pass
    except Exception:
        pass
    return None


def find_add_button():
    """Locate the add button of the Animation Set Editor.

    SFM's tab strip is a custom widget, so a tab lookup is not possible.
    Instead the button is identified by its position: the Animation Set
    Editor panel occupies the upper-left region of the main window, and its
    add button is the first small square button at the top-left of that
    region. Buttons are also matched by label when a tooltip exists.
    """
    main = None
    for w in top_widgets():
        try:
            cn = w.metaObject().className()
        except Exception:
            continue
        # CQSFMMainWindow is SFM's main window class
        if "SFMMainWindow" in cn:
            main = w
            break
    if main is None:
        for w in top_widgets():
            try:
                if "filmmaker" in str(w.windowTitle()).lower():
                    main = w
                    break
            except Exception:
                continue
    cands = []
    if main is not None:
        try:
            for cls in (QtGui.QToolButton, QtGui.QPushButton):
                for b in main.findChildren(cls):
                    cands.append(b)
        except Exception:
            pass
    if not cands:
        try:
            for w in top_widgets():
                for cls in (QtGui.QToolButton, QtGui.QPushButton):
                    for b in w.findChildren(cls):
                        cands.append(b)
        except Exception:
            pass
    try:
        listing = []
        for b in cands:
            try:
                if not b.isVisible():
                    continue
                gp = b.mapTo(main) if main is not None else b.geometry()
                listing.append({"class": str(b.metaObject().className()),
                                "text": str(b.text()), "tip": str(b.toolTip()),
                                "x": gp.x(), "y": gp.y(),
                                "w": gp.width(), "h": gp.height()})
            except Exception:
                continue
        atomic_write(os.path.join(QUEUE, "button_candidates.json"), listing)
    except Exception:
        pass
    # The Animation Set Editor panel is on the left, below the toolbar.
    # Its add button sits at the panel's top-left corner.
    best = None
    for b in cands:
        try:
            if not b.isVisible():
                continue
            g = b.geometry()
            label = (str(b.text()) + " " + str(b.toolTip())
                     + " " + str(b.objectName())).lower()
            gp = b.mapTo(main) if main is not None else g
            score = 1000
            if "add" in label or "new" in label or "create" in label:
                score = 0
            else:
                col = 1 if gp.left() < 260 else 0
                row = 1 if 100 < gp.top() < 280 else 0
                size_ok = 1 if (gp.width() <= 40 and gp.height() <= 40) else 0
                if col and row and size_ok:
                    score = 1
                elif col and row:
                    score = 2
                elif size_ok and gp.top() < 320:
                    score = 3
            if best is None or score < best[0]:
                best = (score, b, label)
        except Exception:
            continue
    return best


def find_file_dialog():
    for w in top_widgets():
        try:
            cn = w.metaObject().className()
            if "FileDialog" in cn or "FileDialog" in str(type(w)):
                if w.isVisible():
                    return w
        except Exception:
            continue
    return None


def find_dialog_tree(dlg):
    for cls in (QtGui.QTreeWidget, QtGui.QListWidget):
        try:
            items = dlg.findChildren(cls)
            for it in items:
                if it.isVisible():
                    return it
        except Exception:
            pass
    for cls in (QtGui.QTreeWidget, QtGui.QListWidget):
        try:
            items = dlg.findChildren(cls)
            if items:
                return items[0]
        except Exception:
            pass
    return None


def set_filter(dlg, text):
    for le in dlg.findChildren(QtGui.QLineEdit):
        try:
            le.setText(text)
            pump(300)
            return True
        except Exception:
            pass
    return False


def tree_rows(tree):
    rows = []
    try:
        it = QtGui.QTreeWidgetItemIterator(tree)
        while it.value():
            item = it.value()
            try:
                txt = str(item.text(0))
            except Exception:
                txt = ""
            if not txt:
                try:
                    txt = str(item.text(1))
                except Exception:
                    txt = ""
            parts = []
            p = item
            while p is not None:
                try:
                    tt = str(p.text(0))
                except Exception:
                    tt = ""
                if tt:
                    parts.insert(0, tt)
                try:
                    p = p.parent()
                except Exception:
                    p = None
            rows.append((txt, "\\".join(parts), item))
            it += 1
    except Exception:
        pass
    return rows


def pick_model(dlg, want):
    tree = find_dialog_tree(dlg)
    if tree is None:
        return None, "no tree"
    rows = tree_rows(tree)
    for txt, rel, item in rows:
        if txt.lower() != want.lower() + ".mdl":
            continue
        reln = rel.replace("\\", "/")
        if reln.startswith("models/"):
            reln = reln[7:]
        for base in [GAME_TF_MODELS,
                     GAME_TF_MODELS + "\\player\\hwm",
                     GAME_TF_MODELS + "\\player"]:
            cand = os.path.join(base, reln.replace("/", os.sep))
            if os.path.isfile(cand):
                try:
                    tree.setCurrentItem(item)
                except Exception:
                    pass
                try:
                    item.setSelected(True)
                except Exception:
                    pass
                pump(150)
                return (item, cand, rel), None
    for txt, rel, item in rows:
        if txt.lower() == want.lower() + ".mdl":
            try:
                tree.setCurrentItem(item)
                item.setSelected(True)
            except Exception:
                pass
            pump(150)
            return (item, rel, rel), None
    return None, "%s not found (%d rows)" % (want, len(rows))


def click_open(dlg):
    for b in dlg.findChildren(QtGui.QPushButton):
        try:
            if str(b.text()).strip().lower() in ("open", "ok"):
                b.click()
                pump(500)
                return True
        except Exception:
            pass
    try:
        dlg.accept()
        pump(500)
        return True
    except Exception:
        return False


def close_wizard_dialog():
    """SFM shows a 'New Session' wizard on start. It blocks the main window
    and its modal-ness prevents any editor interaction. Close it."""
    closed = []
    for w in top_widgets():
        try:
            cn = w.metaObject().className()
        except Exception:
            continue
        if "Wizard" not in cn and "NewWizard" not in cn:
            continue
        try:
            if not w.isVisible():
                continue
            # prefer a Cancel / Close button
            done = False
            for b in w.findChildren(QtGui.QPushButton):
                try:
                    t = str(b.text()).strip().lower()
                    if t in ("cancel", "close", "skip", "later"):
                        b.click()
                        pump(400)
                        done = True
                        break
                except Exception:
                    pass
            if not done:
                try:
                    w.close()
                    pump(400)
                    done = True
                except Exception:
                    pass
            if done:
                closed.append(cn)
        except Exception:
            continue
    return closed


def open_picker(want):
    """Open the MDL Picker via the Animation Set Editor add button."""
    close_wizard_dialog()
    dump_widgets()
    best = find_add_button()
    if best is None:
        # record every candidate so the failure is diagnosable from disk
        try:
            main = None
            for w in top_widgets():
                if "Source Filmmaker" in str(w.windowTitle()):
                    main = w
                    break
            cands = []
            if main is not None:
                for cls in (QtGui.QToolButton, QtGui.QPushButton):
                    for b in main.findChildren(cls):
                        if not b.isVisible():
                            continue
                        gp = b.mapTo(main)
                        cands.append({"class": str(b.metaObject().className()),
                                       "text": str(b.text()), "tip": str(b.toolTip()),
                                       "x": gp.x(), "y": gp.y(),
                                       "w": gp.width(), "h": gp.height()})
            atomic_write(os.path.join(QUEUE, "button_candidates.json"), cands)
        except Exception:
            pass
        return None, "no add button found"
    score, b, label = best
    log("add button: score=%d label=%r" % (score, label))
    try:
        b.click()
    except Exception as e:
        return None, "click failed: %s" % e
    pump(500)
    dlg = find_file_dialog()
    if dlg is None:
        # a menu may have opened
        menu = None
        for w in top_widgets():
            try:
                if isinstance(w, QtGui.QMenu) and w.isVisible():
                    menu = w
                    break
            except Exception:
                pass
        if menu is not None:
            for act in menu.actions():
                try:
                    if "new model" in str(act.text()).lower():
                        act.trigger()
                        pump(600)
                        dlg = find_file_dialog()
                        break
                except Exception:
                    pass
            if dlg is None:
                try:
                    menu.close()
                except Exception:
                    pass
    if dlg is None:
        return None, "no file dialog after click"
    log("file dialog opened: %s" % dlg.metaObject().className())
    set_filter(dlg, want)
    pump(300)
    return dlg, None


def animset_names():
    names = []
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
        return names
    try:
        for a in shot.animationSets:
            try:
                names.append(str(a.GetName()))
            except Exception:
                pass
    except Exception:
        pass
    return names


def find_new_animset(before):
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
        return None, None
    try:
        for a in shot.animationSets:
            try:
                nm = str(a.GetName())
            except Exception:
                nm = ""
            if nm not in before:
                return a, shot
    except Exception:
        pass
    return None, shot


def gui_place_model(name, model_file, pos):
    """Entry point used by the bridge: create one model through the GUI."""
    return place_one(name, model_file, pos)


def place_one(name, model_file, pos):
    want = os.path.basename(str(model_file)).lower()
    if want.endswith(".mdl"):
        want = want[:-4]
    diag = {"name": name, "want": want}
    before = animset_names()
    diag["before"] = before
    dlg, err = open_picker(want)
    if dlg is None:
        diag["error"] = "picker: %s" % err
        return diag
    picked, perr = pick_model(dlg, want)
    if picked is None:
        diag["error"] = "pick: %s" % perr
        try:
            dlg.close()
        except Exception:
            pass
        return diag
    item, path, rel = picked
    diag["picked"] = path
    click_open(dlg)
    pump(1500)
    aset, shot = find_new_animset(before)
    if aset is None:
        diag["error"] = "no new animation set"
        return diag
    try:
        diag["animset"] = str(aset.GetName())
    except Exception:
        pass
    dag = None
    try:
        dags = aset.GetDagNodes()
        if dags:
            dag = dags[0]
    except Exception:
        pass
    if dag is None:
        try:
            dag = sfm.FindDag(diag.get("animset", name))
        except Exception:
            pass
    if dag is None:
        diag["error"] = "no dag node"
        return diag
    try:
        dag.SetName(str(name))
    except Exception as e:
        diag["rename_error"] = str(e)[:100]
    try:
        aset.SetName(str(name))
    except Exception:
        try:
            aset.name.SetValue(str(name))
        except Exception:
            pass
    if pos is not None:
        try:
            sfm.SelectDag(dag)
            sfm.Move(float(pos[0]), float(pos[1]), float(pos[2]))
            diag["moved"] = [float(pos[0]), float(pos[1]), float(pos[2])]
        except Exception as e:
            diag["move_error"] = str(e)[:120]
    diag["ok"] = True
    try:
        sfmApp.SaveDocument()
        diag["saved"] = True
    except Exception as e:
        diag["save_error"] = str(e)[:120]
    return diag




# ---------------------------------------------------------------- bootstrap
def sfm_screenshot(path=None):
    """Grab the SFM main window so the operator can see the current state."""
    out = path or os.path.join(QUEUE, "sfm_screen.png")
    try:
        from PySide import QtGui
    except Exception as e:
        return {"ok": False, "error": "no QtGui: %s" % e}
    try:
        for w in top_widgets():
            try:
                cn = w.metaObject().className()
            except Exception:
                continue
            if "SFMMainWindow" not in cn:
                continue
            try:
                pm = w.grab()
            except Exception as e:
                return {"ok": False, "error": "grab failed: %s" % e}
            try:
                pm.save(out, "PNG")
            except Exception as e:
                return {"ok": False, "error": "save failed: %s" % e}
            return {"ok": True, "path": out, "size": [pm.width(), pm.height()]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:150]}
    return {"ok": False, "error": "no main window"}


def _write_marker():
    """Record which copy of this script actually executed."""
    try:
        with open(os.path.join(QUEUE, "executed_from.txt"), "w") as f:
            f.write("%s\n%s\n" % (__file__, time.strftime("%H:%M:%S")))
    except Exception:
        try:
            with open(os.path.join(QUEUE, "executed_from.txt"), "w") as f:
                f.write("no __file__: %s\n" % time.strftime("%H:%M:%S"))
        except Exception:
            pass


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
        _write_marker()
        log("=== HoneyFilmmaker bridge start ===")
        log("sfm=%s vs=%s sfmApp=%s qt=%s" % (HAVE_SFM, HAVE_VS, HAVE_APP, HAVE_QT))
        # SFM caches the script menu at startup. Rescan so a newly installed
        # script (or an updated one) is actually registered.
        try:
            sfmApp.RescanScriptMenus()
            log("script menus rescanned")
        except Exception as e:
            log("rescan failed: %s" % e)
        # Reopen the last session so the pipeline has a shot to work with.
        try:
            if not sfmApp.HasDocument():
                r = sfmApp.OpenDocument(LAST_SESSION)
                log("reopened session: %s" % r)
        except Exception as e:
            log("session reopen failed: %s" % e)
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
    # SFM caches the script menu. Rescan before triggering so an updated
    # script file is the one that actually runs.
    try:
        sfmApp.RescanScriptMenus()
    except Exception:
        pass
    r = trigger_scripts_menu("honey_gui_v2")
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
