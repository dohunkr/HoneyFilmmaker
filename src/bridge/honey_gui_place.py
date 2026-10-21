# -*- coding: utf-8 -*-
# HoneyFilmmaker GUI model placer - v2
# INSTALL AS: game/usermod/scripts/sfm/mainmenu/honey_gui_v1.py
#
# Rea-verified facts about SFM (ifm.dll strings):
#   - "CAnimationSetEditor::CreateAnimationSetForModel: unable to get
#      studiohdr_t for model %s"
#   - "CAnimationSetEditor::CreateAnimationSetForModel: model has no facial
#      animation model %s [%s]"
#   - "MDL file contains no sequences"
#   - CQMDLPickerDialog::SelectModelAndCreateAnimationSetWithDialogAccepted
#   => SFM's real model creation goes through the MDL Picker dialog.
#      sfm.CreateModel() returns None from script contexts, so the GUI path
#      is the only reliable one.
#
# This file is executed from the Scripts menu (mainmenu context) and drives
# the real SFM UI with Qt.

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
BTN_DUMP = os.path.join(QUEUE, "widgets.json")
GAME_TF_MODELS = r"D:\SteamLibrary\steamapps\common\SourceFilmmaker\game\tf\models"


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
    """Full inventory of every visible widget that could be the add button."""
    inv = []
    try:
        app = QtGui.QApplication.instance()
    except Exception:
        return inv
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
                if cn not in ("QToolButton", "QPushButton", "QTabWidget",
                              "QTabBar", "QStackedWidget", "QDockWidget",
                              "QListView", "QTreeView"):
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
                inv.append(info)
            except Exception:
                continue
    return inv


def dump_widgets():
    inv = widget_inventory()
    atomic_write(BTN_DUMP, inv)
    return inv


def find_anim_set_tab():
    """Return the widget of the Animation Set Editor tab."""
    for w in top_widgets():
        try:
            for tb in w.findChildren(QtGui.QTabWidget):
                for i in range(tb.count()):
                    if "animation set" in str(tb.tabText(i)).lower():
                        return tb.widget(i)
        except Exception:
            continue
    for w in top_widgets():
        try:
            if "animation set" in str(w.windowTitle()).lower():
                return w
        except Exception:
            continue
    return None


def find_add_button():
    """The add button in the Animation Set Editor.
    It is the top-left small square button of that panel."""
    panel = find_anim_set_tab()
    cands = []
    if panel is not None:
        try:
            for cls in (QtGui.QToolButton, QtGui.QPushButton):
                for b in panel.findChildren(cls):
                    cands.append(b)
        except Exception:
            pass
    if not cands:
        # fall back: every tool button in the app that is small and top-left
        try:
            for w in top_widgets():
                for b in w.findChildren(QtGui.QToolButton):
                    cands.append(b)
        except Exception:
            pass
    best = None
    for b in cands:
        try:
            if not b.isVisible():
                continue
            g = b.geometry()
            label = (str(b.text()) + " " + str(b.toolTip())
                     + " " + str(b.objectName())).lower()
            score = 100
            if "add" in label or "new" in label or "create" in label or "+" in label:
                score = 0
            elif g.top() < 30 and g.left() < 30:
                score = 1
            elif g.top() < 30:
                score = 2
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


def open_picker(want):
    """Open the MDL Picker via the Animation Set Editor add button."""
    dump_widgets()
    best = find_add_button()
    if best is None:
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


def main():
    for d in (QUEUE, INBOX, OUTBOX):
        if not os.path.isdir(d):
            try:
                os.makedirs(d)
            except Exception:
                pass
    atomic_write(HEARTBEAT, {"ts": time.time(), "ctx": "gui2",
                              "have_qt": HAVE_QT, "have_sfm": HAVE_SFM,
                              "have_app": HAVE_APP, "pid": os.getpid()})
    try:
        with open(os.path.join(QUEUE, "which_script.txt"), "w") as f:
            f.write("GUI-PLACER v2 pid=%s %s\n"
                    % (os.getpid(), time.strftime("%H:%M:%S")))
    except Exception:
        pass
    log("GUI-PLACER v2 running")
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
        if cname == "add_model":
            try:
                res = place_one(params.get("name", "model"),
                                params.get("model_file")
                                or params.get("asset_path", ""),
                                params.get("pos"))
            except Exception:
                res = {"ok": False, "error": traceback.format_exc(limit=3)}
        elif cname == "ping":
            res = {"ok": True, "result": {"ctx": "gui2"}}
        elif cname == "scan_dags":
            res = {"ok": True, "dags": widget_inventory()[:80]}
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
    log("gui2 batch: %d ok, %d failed" % (done, failed))


try:
    main()
except Exception:
    log("error: %s" % traceback.format_exc(limit=3))
