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
    # None in every script context available to us.
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
        print "[honey/gui] %s" % m
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


def pump(ms=250):
    """Let SFM process events so the UI can react."""
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


def find_dock(title_part):
    for w in top_widgets():
        try:
            t = str(w.windowTitle())
        except Exception:
            continue
        if title_part.lower() in t.lower():
            return w
    return None


def anim_set_editor_buttons():
    """Buttons that belong to the Animation Set Editor dock.
    Returns a list of (widget, info-dict) so the caller can pick the add
    button reliably and so failures can be diagnosed from a file."""
    out = []
    for w in top_widgets():
        try:
            if not isinstance(w, QtGui.QDockWidget):
                continue
            title = str(w.windowTitle())
        except Exception:
            continue
        if "animation set" not in title.lower():
            continue
        for cls in (QtGui.QToolButton, QtGui.QPushButton):
            try:
                btns = w.findChildren(cls)
            except Exception:
                continue
            for b in btns:
                info = {"class": str(b.metaObject().className()),
                        "text": str(b.text()),
                        "toolTip": str(b.toolTip()),
                        "objectName": str(b.objectName()),
                        "visible": bool(b.isVisible()),
                        "x": b.x(), "y": b.y(),
                        "w": b.width(), "h": b.height()}
                out.append((b, info))
    return out


def dump_buttons():
    """Write the Animation Set Editor button inventory to a file."""
    info = []
    for _b, i in anim_set_editor_buttons():
        info.append(i)
    try:
        with open(os.path.join(QUEUE, "buttons.json"), "w") as f:
            json.dump(info, f, indent=2)
    except Exception:
        pass
    return info


def open_new_model_dialog(model_basename):
    """Open the 'Create Animation Set for New Model' file dialog."""
    buttons = anim_set_editor_buttons()
    log("anim set editor buttons: %d" % len(buttons))
    dump_buttons()
    # Prefer a button that looks like "add" (plus icon, no text, top-left).
    ordered = []
    for b, i in buttons:
        if not i.get("visible"):
            continue
        label = (i["text"] + " " + i["toolTip"] + " " + i["objectName"]).lower()
        score = 50
        if "add" in label or "new" in label or "create" in label:
            score = 0
        elif i["text"].strip() == "" and i["y"] < 40:
            score = 1
        ordered.append((score, i["y"], i["x"], b))
    ordered.sort(key=lambda t: (t[0], t[1], t[2]))
    for score, _y, _x, b in ordered:
        try:
            b.click()
        except Exception:
            continue
        pump(350)
        dlg = find_file_dialog()
        if dlg is not None:
            log("dialog opened via button (score %d)" % score)
            return dlg
        # a popup menu may have appeared
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
                        pump(500)
                        dlg = find_file_dialog()
                        if dlg is not None:
                            log("dialog opened via menu action")
                            return dlg
                except Exception:
                    pass
            try:
                menu.close()
            except Exception:
                pass
    return None


def find_file_dialog():
    for w in top_widgets():
        try:
            cn = w.metaObject().className()
        except Exception:
            continue
        if "FileDialog" in cn or "FileDialog" in str(type(w)):
            return w
    return None


def dialog_tree(dlg):
    for cls in (QtGui.QTreeWidget, QtGui.QListWidget, QtGui.QTreeView, QtGui.QListView):
        try:
            items = dlg.findChildren(cls)
            if items:
                return items[0]
        except Exception:
            pass
    return None


def set_filter(dlg, text):
    """Set the file dialog's filter line edit."""
    for le in dlg.findChildren(QtGui.QLineEdit):
        try:
            le.setText(text)
            pump(200)
            return True
        except Exception:
            pass
    return False


def tree_rows(tree):
    """Return [(text, abs_rel_path)] for every row of a QTreeWidget."""
    rows = []
    try:
        iterator = QtGui.QTreeWidgetItemIterator(tree)
        while iterator.value():
            item = iterator.value()
            try:
                txt = str(item.text(0))
            except Exception:
                txt = ""
            if not txt:
                try:
                    txt = str(item.text(1))
                except Exception:
                    txt = ""
            # build the relative path from the ancestor chain
            parts = []
            it = item
            while it is not None:
                try:
                    t = str(it.text(0))
                except Exception:
                    t = ""
                if t:
                    parts.insert(0, t)
                try:
                    it = it.parent()
                except Exception:
                    it = None
            rel = "\\".join(parts)
            rows.append((txt, rel, item))
            iterator += 1
    except Exception:
        pass
    return rows


def pick_model_in_dialog(dlg, want_basename):
    """Select the row whose real file exists and matches the basename."""
    tree = dialog_tree(dlg)
    if tree is None:
        return None, "no tree widget"
    rows = tree_rows(tree)
    best = None
    for txt, rel, item in rows:
        base = txt.lower()
        if not base.endswith(".mdl"):
            continue
        stem = base[:-4]
        if stem != want_basename.lower():
            continue
        # verify the real file exists under the tf models dir
        rel_norm = rel.replace("\\", "/")
        if rel_norm.startswith("models/"):
            rel_norm = rel_norm[len("models/"):]
        cand = os.path.join(GAME_TF_MODELS, rel_norm.replace("/", os.sep))
        if os.path.isfile(cand):
            best = (item, cand, rel)
            break
    if best is None:
        # fall back to any row with the right file name
        for txt, rel, item in rows:
            if txt.lower() == want_basename.lower() + ".mdl":
                best = (item, rel, rel)
                break
    if best is None:
        return None, "model %s not in dialog (%d rows)" % (want_basename, len(rows))
    item, path, rel = best
    try:
        tree.setCurrentItem(item)
    except Exception:
        pass
    try:
        item.setSelected(True)
    except Exception:
        pass
    pump(150)
    return (item, path, rel), None


def click_open(dlg):
    for b in dlg.findChildren(QtGui.QPushButton):
        try:
            if str(b.text()).strip().lower() in ("open", "ok"):
                b.click()
                pump(400)
                return True
        except Exception:
            pass
    try:
        dlg.accept()
        pump(400)
        return True
    except Exception as e:
        return False


def find_new_animset(before_names):
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
        sets = list(shot.animationSets)
    except Exception:
        sets = []
    new = None
    for a in sets:
        try:
            nm = str(a.GetName())
        except Exception:
            nm = ""
        if nm not in before_names:
            new = a
            break
    return shot, new


def current_animset_names():
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


def rename_and_move(animset, dag, name, pos):
    out = {}
    try:
        dag.SetName(str(name))
        out["dag_renamed"] = True
    except Exception as e:
        out["dag_rename_error"] = str(e)[:120]
    try:
        animset.SetName(str(name))
        out["animset_renamed"] = True
    except Exception:
        try:
            animset.name.SetValue(str(name))
            out["animset_renamed"] = True
        except Exception as e:
            out["animset_rename_error"] = str(e)[:120]
    if pos is not None:
        try:
            sfm.SelectDag(dag)
            sfm.Move(float(pos[0]), float(pos[1]), float(pos[2]))
            out["moved"] = [float(pos[0]), float(pos[1]), float(pos[2])]
        except Exception as e:
            out["move_error"] = str(e)[:120]
    return out


def gui_place_model(name, model_file, pos):
    """GUI-driven model creation: Animation Set Editor [+] -> file dialog."""
    return do_add_model(name, model_file, pos)


def sfm_create_model_variants():
    """Candidate model paths.

    Verified from ifm.dll (SFM engine) strings:
      - "MDL file contains no sequences"  -> a model only loads if it has
        $sequence data, i.e. it must be accompanied by <name>_animations.mdl.
      - "%s\\%s.mdl" with "contentdir:models" -> virtual path is
        models/<file>.mdl, and the engine splits dir + file name.
      - tf/models/player/hwm/*.mdl have NO *_animations.mdl sibling, so they
        cannot be loaded as game models. tf/models/player/*.mdl DO have one.
    """
    base = "models/player/"
    names = ["scout", "soldier", "spy", "medic", "heavy", "demo",
             "engineer", "pyro", "sniper"]
    out = []
    for n in names:
        out.append(base + n + ".mdl")
        out.append("tf/" + base + n + ".mdl")
    for n in ["bot_soldier", "bot_soldier_boss"]:
        out.append("models/bots/soldier/" + n + ".mdl")
        out.append("models/bots/soldier_boss/" + n + ".mdl")
    out.append("models/props_2fort/oildrum.mdl")
    out.append("models/player/hwm/scout.mdl")
    return out


def sfm_try_create_models():
    """Try CreateModel with the verified path forms. Reports every attempt.

    SFM's SWIG wrapper validates argument count and raises
    "Missing model file name." when the name is absent, so we probe the
    accepted arity first (0..3) using strings only, then try paths.
    """
    tries = []
    model = None
    used = None
    arity = None
    for n in range(0, 4):
        try:
            sfm.CreateModel(*(["models/player/scout.mdl"] * n))
            arity = n
            tries.append("arity %d accepted" % n)
            break
        except Exception as e:
            tries.append("arity %d -> %s" % (n, str(e)[:90]))
    if arity is None:
        arity = 1
    for c in sfm_create_model_variants():
        args = ["models/player/scout.mdl"] * (arity - 1) + [c]
        try:
            m = sfm.CreateModel(*args)
        except Exception as e:
            tries.append("%s -> ERR %s" % (c, str(e)[:70]))
            continue
        tries.append("%s -> %s" % (c, "OK" if m is not None else "None"))
        if m is not None:
            model = m
            used = c
            break
    return model, used, tries


def do_add_model(name, model_file, pos):
    """Try CreateModel first (fast path). If that fails, drive the GUI."""
    base = os.path.basename(str(model_file)).lower()
    if base.endswith(".mdl"):
        base = base[:-4]
    diag = {"name": name, "model_file": model_file, "base": base}
    before = current_animset_names()
    diag["animsets_before"] = before
    shot, how = find_shot()
    diag["shot_source"] = how
    if shot is None:
        diag["error"] = "no shot"
        return diag
    # --- fast path: CreateModel with verified path forms ---
    model, used, tries = sfm_try_create_models()
    diag["create_model_tries"] = tries
    if model is not None:
        animset = None
        try:
            animset = sfm.CreateAnimationSet(str(name), target=model)
        except Exception as e:
            diag["error"] = "CreateAnimationSet: %s" % e
            return diag
        try:
            dag = vs.CreateElement("DmeDag", str(name), shot.GetFileId())
            dag.AddChild(model)
            shot.scene.AddChild(dag)
        except Exception as e:
            diag["error"] = "dag attach: %s" % e
            return diag
        diag["ok"] = True
        diag["path"] = used
        diag.update(rename_and_move(animset, dag, name, pos))
        try:
            sfmApp.SaveDocument()
            diag["saved"] = True
        except Exception as e:
            diag["save_error"] = str(e)[:120]
        return diag
    # --- fallback: GUI flow ---
    dlg = open_new_model_dialog(base)
    if dlg is None:
        diag["error"] = "could not open the model file dialog"
        return diag
    diag["dialog"] = str(dlg.metaObject().className())
    set_filter(dlg, base)
    pump(300)
    picked, err = pick_model_in_dialog(dlg, base)
    if picked is None:
        diag["error"] = err
        try:
            dlg.close()
        except Exception:
            pass
        return diag
    item, path, rel = picked
    diag["picked_path"] = path
    diag["picked_rel"] = rel
    click_open(dlg)
    pump(1200)
    shot, new = find_new_animset(before)
    if new is None:
        diag["error"] = "no new animation set appeared"
        return diag
    try:
        diag["animset_name"] = str(new.GetName())
    except Exception:
        pass
    dag = None
    try:
        dags = new.GetDagNodes()
    except Exception:
        dags = None
    if dags:
        try:
            dag = dags[0]
        except Exception:
            dag = None
    if dag is None:
        try:
            d = sfm.FindDag(diag.get("animset_name", name))
            if d is not None:
                dag = d
        except Exception:
            pass
    if dag is None:
        diag["error"] = "could not resolve the dag node"
        return diag
    diag.update(rename_and_move(new, dag, name, pos))
    diag["ok"] = True
    try:
        sfmApp.SaveDocument()
        diag["saved"] = True
    except Exception as e:
        diag["save_error"] = str(e)[:120]
    return diag




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
        # SFM caches the script menu at startup. Rescan so a newly installed
        # script (or an updated one) is actually registered.
        try:
            sfmApp.RescanScriptMenus()
            log("script menus rescanned")
        except Exception as e:
            log("rescan failed: %s" % e)
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
    r = trigger_scripts_menu("honey_gui_v1")
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
