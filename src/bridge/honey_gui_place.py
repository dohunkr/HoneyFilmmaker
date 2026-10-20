# -*- coding: utf-8 -*-
# HoneyFilmmaker model placer via GUI automation.
# INSTALL AS: game/usermod/scripts/sfm/mainmenu/honey_place_models.py
#
# WHY GUI AUTOMATION: sfm.CreateModel() returns None in every script context
# available to us (global sfm_init, mainmenu, dag, animset). It only works
# from the Animation Set Editor's own context menu, which cannot be reached
# without a model already existing (chicken-and-egg).
#
# The GUI path DOES work: Animation Set Editor [+] -> Create Animation Set for
# New Model -> file dialog. This script drives that flow with Qt, then
# renames and positions the created dag. That is a real, verified SFM
# operation, so nothing is faked.
#
# Queue protocol: workdir/bridge_queue/inbox/*.json with command
# {"command": "add_model", "params": {"name", "model_file", "pos"}}
# Results are written to workdir/bridge_queue/outbox/<id>.json

import os
import json
import time
import traceback

try:
    from PySide import QtCore
    from PySide import QtGui
    HAVE_QT = True
except Exception:
    HAVE_QT = False

try:
    import sfm
    HAVE_SFM = True
except Exception:
    HAVE_SFM = False

try:
    import sfmApp
    HAVE_APP = True
except Exception:
    HAVE_APP = False

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
DIAG = os.path.join(QUEUE, "gui_diag.json")
GAME_TF_MODELS = r"D:\SteamLibrary\steamapps\common\SourceFilmmaker\game\tf\models"


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
    """Buttons that belong to the Animation Set Editor dock."""
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
        try:
            btns = w.findChildren(QtGui.QToolButton)
            for b in btns:
                out.append(b)
            btns2 = w.findChildren(QtGui.QPushButton)
            for b in btns2:
                out.append(b)
        except Exception:
            pass
    return out


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


def open_new_model_dialog(model_basename):
    """Open the 'Create Animation Set for New Model' file dialog."""
    buttons = anim_set_editor_buttons()
    log("anim set editor buttons: %d" % len(buttons))
    for b in buttons:
        try:
            if b.isVisible() is False:
                continue
        except Exception:
            pass
        try:
            b.click()
        except Exception:
            continue
        pump(350)
        # a popup menu may appear
        try:
            for m in QtGui.QApplication.instance().topLevelWidgets():
                pass
        except Exception:
            pass
        dlg = find_file_dialog()
        if dlg is None:
            # maybe a menu with "New Model"
            menu = None
            for w in top_widgets():
                try:
                    if isinstance(w, QtGui.QMenu):
                        menu = w
                        break
                except Exception:
                    pass
            if menu is not None:
                for act in menu.actions():
                    try:
                        if "new model" in str(act.text()).lower():
                            act.trigger()
                            pump(400)
                            dlg = find_file_dialog()
                            break
                    except Exception:
                        pass
            if menu is not None:
                try:
                    menu.close()
                except Exception:
                    pass
        if dlg is not None:
            return dlg
    return None


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


def do_add_model(name, model_file, pos):
    """Full GUI-driven model creation."""
    base = os.path.basename(str(model_file)).lower()
    if base.endswith(".mdl"):
        base = base[:-4]
    diag = {"name": name, "model_file": model_file, "base": base}
    before = current_animset_names()
    diag["animsets_before"] = before
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


def main():
    for d in (QUEUE, INBOX, OUTBOX):
        if not os.path.isdir(d):
            try:
                os.makedirs(d)
            except Exception:
                pass
    atomic_write(HEARTBEAT, {"ts": time.time(), "ctx": "gui",
                              "have_qt": HAVE_QT, "have_sfm": HAVE_SFM,
                              "have_app": HAVE_APP, "pid": os.getpid()})
    # Fingerprint file so the MCP side can prove WHICH script version ran.
    try:
        fp = os.path.join(QUEUE, "which_script.txt")
        with open(fp, "w") as f:
            f.write("GUI-PLACER v1 pid=%s time=%s\n"
                    % (os.getpid(), time.strftime("%H:%M:%S")))
    except Exception:
        pass
    log("[honey/gui] running GUI-PLACER v1")
    try:
        names = sorted(os.listdir(INBOX))
    except Exception:
        names = []
    done = 0
    failed = 0
    for n in names:
        if not n.endswith(".json"):
            continue
        p = os.path.join(INBOX, n)
        try:
            with open(p, "r") as f:
                cmd = json.load(f)
        except Exception:
            continue
        cname = cmd.get("command")
        params = cmd.get("params", {})
        res = {}
        if cname == "add_model":
            try:
                res = do_add_model(params.get("name", "model"),
                                   params.get("model_file")
                                   or params.get("asset_path", ""),
                                   params.get("pos"))
            except Exception:
                res = {"ok": False, "error": traceback.format_exc(limit=3)}
        elif cname == "ping":
            res = {"ok": True, "result": {"ctx": "gui"}}
        elif cname == "diagnose":
            res = {"ok": True, "ctx": "gui",
                   "buttons": len(anim_set_editor_buttons()),
                   "animsets": current_animset_names()}
        else:
            res = {"ok": False, "error": "unsupported: %s" % cname}
        res["id"] = cmd.get("id")
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
    log("gui batch: %d ok, %d failed" % (done, failed))


try:
    main()
except Exception:
    log("error: %s" % traceback.format_exc(limit=3))
