# SFM in-app bridge poller — Python 2.7 compatible (SFM embedded interpreter).
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
        with open(HEARTBEAT, "w") as f:
            json.dump({"ts": time.time(), "have_sfm": HAVE_SFM}, f)
    except Exception:
        pass


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
            with open(SESSION, "w") as f:
                json.dump({"connected": True, "have_sfm": True,
                           "session_open": bool(session), "ts": time.time(),
                           "last_command": name, "last_params": params}, f)
        except Exception:
            pass
        if name == "ping":
            return {"id": cmd.get("id"), "ok": True, "result": info}
        if name == "get_session":
            return {"id": cmd.get("id"), "ok": True, "result": info}
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


def main(poll_interval=1.0):
    ensure_dirs()
    print("[sfm_bridge] polling %s (HAVE_SFM=%s)" % (INBOX, HAVE_SFM))
    while True:
        heartbeat()
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
                with open(os.path.join(OUTBOX, n), "w") as f:
                    json.dump(res, f, indent=2)
                os.remove(p)
            except Exception:
                pass
        time.sleep(poll_interval)


if __name__ == "__main__":
    main()
