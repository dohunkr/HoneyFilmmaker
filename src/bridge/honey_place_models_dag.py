# -*- coding: utf-8 -*-
# HoneyFilmmaker DAG-context placer.
# INSTALL AS: game/usermod/scripts/sfm/dag/exact/count1/honey_place_models.py
#
# SFM's CreateModel only returns a model when the script runs in the
# dag/animset context (Valve docs: "Python script commands" lists
# global / animset-context / dag-context / sfm_init as separate contexts).
# In the global sfm_init.py context and in the Script Editor it returns None.
#
# This file is reached from the DAG right-click menu (exactly 1 node selected).

import os
import json
import time
import traceback

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

try:
    import sfmApp
    HAVE_APP = True
except Exception:
    HAVE_APP = False

WORKDIR = os.environ.get("HONEY_WORKDIR", r"D:\Github\HoneyFilmmaker\workdir")
QUEUE = os.path.join(WORKDIR, "bridge_queue")
INBOX = os.path.join(QUEUE, "inbox")
OUTBOX = os.path.join(QUEUE, "outbox")
HEARTBEAT = os.path.join(QUEUE, "heartbeat.json")
GD = "D:/SteamLibrary/steamapps/common/SourceFilmmaker/game"


def log(m):
    try:
        print "[honey/dag] %s" % m
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


def candidates():
    """Model paths to try. The virtual path depends on which game folder is
    mounted, so several forms are tried."""
    rels = ["models/player/hwm/scout.mdl", "models/player/hwm/soldier.mdl",
            "models/player/hwm/spy.mdl",
            "models/bots/soldier_boss/bot_soldier_boss.mdl",
            "models/bots/soldier/bot_soldier.mdl",
            "models/props_c17/oildrum001.mdl"]
    out = []
    for r in rels:
        out.append(r)
        out.append("tf/" + r)
        out.append(GD + "/" + r)
        out.append(GD + "/tf/" + r)
    seen = set()
    res = []
    for c in out:
        if c not in seen:
            seen.add(c)
            res.append(c)
    return res


def mdl_cache_probe():
    """Ask the model cache which paths it knows."""
    info = {}
    try:
        info["cache"] = str(vs.g_pStudioModelCache)
    except Exception as e:
        info["cache"] = "ERR " + str(e)[:80]
    try:
        import sfm
        info["sfm_model_fns"] = [x for x in dir(sfm) if "odel" in x.lower()]
    except Exception as e:
        info["sfm_model_fns"] = "ERR " + str(e)[:80]
    return info


def existing_model_paths():
    """Read the model path of every game model already in the session.
    These are the exact strings SFM itself uses, so they are the ground
    truth for what CreateModel expects."""
    found = []
    try:
        shot, _ = find_shot()
    except Exception:
        shot = None
    if shot is None:
        return found
    try:
        sets = shot.animationSets
    except Exception:
        return found
    for aset in sets:
        try:
            gm = aset.gameModel
        except Exception:
            continue
        for attr in ["model", "modelName", "path", "filename", "mdlpath"]:
            try:
                v = gm.GetValue(attr)
                if v:
                    found.append({"animset": str(aset.GetName()), "attr": attr,
                                  "value": str(v)})
            except Exception:
                pass
        # the model element itself often carries the path
        try:
            for el in gm.GetChildren():
                nm = str(el.GetName())
                if nm.lower().endswith(".mdl"):
                    found.append({"animset": str(aset.GetName()),
                                  "child": nm})
        except Exception:
            pass
    return found


def find_shot():
    if HAVE_SFM:
        try:
            s = sfm.GetCurrentShot()
            if s is not None:
                return s, "GetCurrentShot"
        except Exception:
            pass
    if HAVE_APP:
        try:
            s = sfmApp.GetShotAtCurrentTime()
            if s is not None:
                return s, "GetShotAtCurrentTime"
        except Exception:
            pass
        try:
            shots = sfmApp.GetShots()
            if shots:
                return shots[0], "GetShots[0]"
        except Exception:
            pass
    return None, "none"


def place(name, model_path, pos):
    shot, how = find_shot()
    if shot is None:
        return {"ok": False, "code": "NO_SHOT", "error": "no shot (%s)" % how}
    ordered = []
    if model_path:
        ordered.append(model_path)
    for c in candidates():
        if c not in ordered:
            ordered.append(c)

    tried = []
    model = None
    used = None

    def _try_create(path):
        try:
            m = sfm.CreateModel(path)
        except Exception as e:
            tried.append("%s -> ERR %s" % (path, str(e)[:70]))
            return None
        tried.append("%s -> %s" % (path, "OK" if m is not None else "None"))
        return m

    # Pass 1: plain
    for c in ordered:
        m = _try_create(c)
        if m is not None:
            model = m
            used = c
            break

    # Pass 2: sfm docs say CreateModel may need an animation-set context.
    # "UsingAnimationSet: Specify an animation set to be assumed for commands
    #  in which an animation set is not explicitly specified."
    if model is None:
        animset_try = None
        try:
            cur = sfm.GetCurrentAnimationSet()
            if cur is not None:
                animset_try = cur
                tried.append("current animset present: %s" % str(cur.GetName()))
        except Exception as e:
            tried.append("GetCurrentAnimationSet ERR %s" % str(e)[:60])
        if animset_try is None:
            # Build one from the shot's first existing animation set, or make
            # an empty one via CreateAnimationSet with no target.
            try:
                sets = shot.animationSets
                if sets and len(sets) > 0:
                    animset_try = sets[0]
                    tried.append("using shot.animationSets[0]: %s"
                                 % str(animset_try.GetName()))
            except Exception as e:
                tried.append("shot.animationSets ERR %s" % str(e)[:60])
        if animset_try is not None:
            try:
                sfm.UsingAnimationSet(animset_try)
                tried.append("UsingAnimationSet applied")
            except Exception as e:
                tried.append("UsingAnimationSet ERR %s" % str(e)[:70])
            for c in ordered:
                m = _try_create(c)
                if m is not None:
                    model = m
                    used = c
                    break

    if model is None:
        return {"ok": False, "error": "CreateModel failed", "tried": tried[:24]}
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
        except Exception:
            moved = "Move failed"
    return {"ok": True, "name": name, "path": used, "shot": how,
            "animset": animset is not None, "moved": moved, "tried": tried[:10]}


def save():
    if not HAVE_APP:
        return {"ok": False}
    try:
        if not sfmApp.HasDocument():
            return {"ok": False, "error": "no document"}
        sfmApp.SaveDocument()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def main():
    for d in (QUEUE, INBOX, OUTBOX):
        if not os.path.isdir(d):
            try:
                os.makedirs(d)
            except Exception:
                pass
    atomic_write(HEARTBEAT, {"ts": time.time(), "ctx": "dag",
                              "have_sfm": HAVE_SFM, "have_vs": HAVE_VS,
                              "have_app": HAVE_APP, "pid": os.getpid()})
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
                res = place(params.get("name", "model"),
                            params.get("asset_path", ""),
                            params.get("pos"))
            except Exception:
                res = {"ok": False, "error": traceback.format_exc(limit=3)}
        elif cname == "ping":
            res = {"ok": True, "result": {"ctx": "dag"}}
        elif cname == "diagnose":
            shot, how = find_shot()
            res = {"ok": True, "ctx": "dag", "shot_source": how,
                   "shot_name": None if shot is None else str(shot.GetName()),
                   "model_fns": [x for x in dir(sfm) if "odel" in x],
                   "cache": mdl_cache_probe(),
                   "existing_models": existing_model_paths()}
        elif cname == "save":
            res = save()
        else:
            res = {"ok": False, "error": "unsupported in dag ctx: %s" % cname}
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
    log("dag ctx batch: %d ok, %d failed" % (done, failed))


try:
    main()
except Exception:
    log("error: %s" % traceback.format_exc(limit=3))
