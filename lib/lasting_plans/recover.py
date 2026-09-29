"""Recover creation/modification dates after a DOCUMENTED metadata loss.

Never runs on its own: the scanner trusts the filesystem. This is for the case where
the filesystem dates are known to be wrong for a stretch of documents (a backup that
stored no birth times, a migration that reset them), and the user says so.

Evidence, strongest first, and never more than the document itself states:
  * a backup-verified modification time (--mtimes TSV, verdict "exact" only);
  * a labelled date near the top of the text ("**Date:** 2026-08-19", "Created: ...");
  * a date in the first H1;
  * a date in the file name.
A recovered creation date is only accepted when it is EARLIER than what is recorded:
the loss being repaired is dates reset to the copy time, which only ever moved them later.
"""
import csv
import datetime
import os
import re

from . import gitrepo, metadata

_DATE = r"(20\d\d)-(\d\d)-(\d\d)(?:[ T](\d\d):(\d\d))?"
_RX = re.compile(_DATE)
_LABEL = re.compile(r"(?i)^\W*(created|date|datum|written|drafted|erstellt)\W*[:—–-]\W*" + _DATE)
LABEL_LINES = 40


def _ts(m):
    y, mo, d, hh, mm = m.groups()[-5:]
    try:
        dt = datetime.datetime(int(y), int(mo), int(d), int(hh or 0), int(mm or 0))
    except ValueError:
        return None
    return dt.astimezone().timestamp()  # a date written in a plan is local time


def text_date(relpath, text):
    """(timestamp, evidence) for the creation date the document states, or (None, None)."""
    from .classify import first_h1
    for line in text.splitlines()[:LABEL_LINES]:
        m = _LABEL.match(line)
        if m:
            t = _ts(m)
            if t:
                return t, "labelled %r in the text" % line.strip()[:60]
    h1 = first_h1(text)
    m = _RX.search(h1)
    if m and _ts(m):
        return _ts(m), "date in the H1 %r" % h1[:60]
    m = _RX.search(os.path.basename(relpath))
    if m and _ts(m):
        return _ts(m), "date in the file name"
    return None, None


def load_mtimes(path):
    """{source-relative path: timestamp} from a recovery TSV; verdict 'exact' rows only."""
    out = {}
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            if r.get("verdict") != "exact" or not r.get("backup_mtime"):
                continue
            try:
                out[r["path"]] = datetime.datetime.strptime(r["backup_mtime"], "%Y-%m-%d %H:%M").astimezone().timestamp()
            except ValueError:
                continue
    return out


def _mtime_for(sc, mtimes, by_base):
    for p in [sc.get("source_relpath")] + list(sc.get("source_history") or []):
        if p and p in mtimes:
            return mtimes[p], "backup-verified modification time for %s" % p
    base = os.path.basename(sc.get("source_relpath") or sc["archive_relpath"])
    if len(by_base.get(base, [])) == 1:
        p = by_base[base][0]
        return mtimes[p], "backup-verified modification time for %s (matched by file name)" % p
    return None, None


def plan(lib, window_start, window_end, mtimes=None):
    """Proposed changes for documents whose recorded creation date lies in the loss window
    (or is unknown). Pure: reads only."""
    mtimes = mtimes or {}
    by_base = {}
    for p in mtimes:
        by_base.setdefault(os.path.basename(p), []).append(p)
    now = datetime.datetime.now().timestamp()
    out = []
    for d in sorted(lib.docs, key=lambda x: x.sc["archive_relpath"]):
        sc = d.sc
        src = sc.get("created_source") or ""
        if src == "user" or src.startswith("recovered"):
            continue
        cur = metadata.parse_iso(sc["created_utc"]) if sc.get("created_utc") else None
        if cur is not None and not (window_start <= cur < window_end):
            continue
        if not os.path.exists(d.path):
            continue
        with open(d.path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        ch = {"doc": d, "created": None, "modified": None}
        mt, mev = _mtime_for(sc, mtimes, by_base)
        cur_mod = metadata.parse_iso(sc["modified_utc"]) if sc.get("modified_utc") else None
        if mt and (cur_mod is None or mt < cur_mod):
            ch["modified"] = (mt, mev)
        last_edit = ch["modified"][0] if ch["modified"] else cur_mod
        # a document cannot be created after it was last edited, or after what is recorded
        upper = min(x for x in (cur, last_edit, now) if x is not None)
        t, ev = text_date(sc.get("source_relpath") or sc["archive_relpath"], text)
        if t and t <= upper:
            ch["created"] = (t, ev)
        elif mt and mev and cur is not None and cur > mt:
            # no usable stated date, but a creation date later than the recovered last
            # edit is impossible: bound it by that edit and say it is only a bound
            ch["created"] = (mt, "upper bound: " + mev)
        if ch["created"] or ch["modified"]:
            out.append(ch)
    return out


def apply(changes, reason):
    """Write each change to its sidecar and the archive file, one commit per archive."""
    from .engine import _apply_sidecar_meta, sidecar_rel, write_sidecar
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    touched, failed = {}, []
    for ch in changes:
        sc = ch["doc"].sc
        rec = {"reason": reason, "at_utc": stamp}
        if ch["created"]:
            rec["created_was"] = sc.get("created_utc")
            sc["created_utc"] = metadata.utc_iso(ch["created"][0])
            sc["created_source"] = "recovered: " + ch["created"][1]
        if ch["modified"]:
            rec["modified_was"] = sc.get("modified_utc")
            sc["modified_utc"] = metadata.utc_iso(ch["modified"][0])
            sc["modified_source"] = "recovered: " + ch["modified"][1]
        sc.setdefault("date_recovery", []).append(rec)
        write_sidecar(ch["doc"].root, sc)
        bad = _apply_sidecar_meta(ch["doc"].path, sc)
        if bad:
            failed.append((sc["archive_relpath"], bad))
        touched.setdefault(ch["doc"].root, []).append(sidecar_rel(sc["id"]))
    shas = {}
    for root, paths in touched.items():
        if gitrepo.has_identity(root):
            shas[root] = gitrepo.commit_paths(root, paths, "metadata: recover dates for %d document(s) — %s" % (len(paths), reason))
    return shas, failed
