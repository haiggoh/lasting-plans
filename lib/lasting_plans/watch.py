"""Watch-folder mode: react when a document enters, leaves or moves within the watched trees.

macOS/BSD: kqueue vnode events on every directory (not files) in the source tree and
both archive trees. A directory's WRITE/LINK event fires on create, delete and rename
of its entries, which is exactly "enters, leaves, or moves between subdirectories".
File *edits* do not change the directory, so a bounded catch-up scan (interval_seconds)
covers them, as well as anything missed while asleep. Elsewhere: polling only.
"""
import os
import select
import time

from . import config as cfgmod
from . import engine

DEBOUNCE = 1.5


def _dirs(root):
    out = []
    if not os.path.isdir(root):
        return out
    for d, dirs, _ in os.walk(root, followlinks=False):
        dirs[:] = [x for x in dirs if not x.startswith(".") and not os.path.islink(os.path.join(d, x))]
        out.append(d)
    return out


class KqueueWatcher:
    FLAGS = 0

    def __init__(self, roots):
        self.kq = select.kqueue()
        self.roots = roots
        self.fds = {}
        self.FLAGS = (select.KQ_NOTE_WRITE | select.KQ_NOTE_DELETE | select.KQ_NOTE_EXTEND
                      | select.KQ_NOTE_RENAME | select.KQ_NOTE_LINK)
        self.rearm()

    def rearm(self):
        want = set()
        for r in self.roots:
            want.update(_dirs(r))
            parent = os.path.dirname(r)
            if not os.path.isdir(r) and os.path.isdir(parent):
                want.add(parent)  # wait for the root itself to appear
        for d in list(self.fds):
            if d not in want:
                os.close(self.fds.pop(d))
        evs = []
        for d in want - set(self.fds):
            try:
                fd = os.open(d, getattr(os, "O_EVTONLY", os.O_RDONLY))
            except OSError:
                continue
            self.fds[d] = fd
            evs.append(select.kevent(fd, filter=select.KQ_FILTER_VNODE,
                                     flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR, fflags=self.FLAGS))
        if evs:
            self.kq.control(evs, 0, 0)

    def wait(self, timeout):
        return bool(self.kq.control(None, 64, timeout))

    def close(self):
        for fd in self.fds.values():
            os.close(fd)
        self.kq.close()


def _log(msg):
    print("%s %s" % (time.strftime("%Y-%m-%dT%H:%M:%S"), msg), flush=True)


def _run_scan(reason):
    try:
        lib = engine.Library()
        res = engine.scan(lib)
    except engine.Busy:
        _log("scan skipped (%s): another scan holds the lock" % reason)
        return
    except Exception as e:  # keep the daemon alive; the next pass retries
        _log("scan FAILED (%s): %s" % (reason, e))
        return
    if res.events or res.pending or res.errors:
        _log("scan (%s): %d change(s), %d pending, %d error(s)" % (reason, len(res.events), len(res.pending), len(res.errors)))
        for e in res.events:
            _log("  %s %s %s" % (e[0], e[2], e[3]))
        for p in res.pending + res.errors:
            _log("  ! %s: %s" % p)


def run(once=False, max_seconds=None):
    cfg = cfgmod.load()
    interval = cfg["interval_seconds"]
    lib = engine.Library(cfg)
    roots = [lib.source] + list(lib.roots.values())
    _log("watching %s (+ archives), catch-up every %ds" % (lib.source, interval))
    _run_scan("start")
    if once:
        return
    watcher = KqueueWatcher(roots) if hasattr(select, "kqueue") else None
    start = last = time.monotonic()
    pending_since = None
    try:
        while True:
            if max_seconds and time.monotonic() - start > max_seconds:
                return
            if pending_since is not None:
                timeout = max(0.0, DEBOUNCE - (time.monotonic() - pending_since))
            else:
                timeout = max(1.0, interval - (time.monotonic() - last))
            if max_seconds:
                # never sleep past the deadline, or an idle watcher waits out the full interval
                timeout = max(0.0, min(timeout, max_seconds - (time.monotonic() - start)))
            fired = watcher.wait(timeout) if watcher else (time.sleep(min(timeout, 30)) or False)
            now = time.monotonic()
            if fired:
                pending_since = pending_since or now
                continue
            if pending_since is not None and now - pending_since >= DEBOUNCE:
                pending_since = None
                # a settling file is retried by the stable-read rule; give it one more beat
                _run_scan("change")
                if watcher:
                    watcher.rearm()
                last = time.monotonic()
                continue
            if now - last >= interval:
                _run_scan("interval")
                if watcher:
                    watcher.rearm()
                last = time.monotonic()
    finally:
        if watcher:
            watcher.close()
