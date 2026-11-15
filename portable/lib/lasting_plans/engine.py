"""The preservation engine. Every frontend (CLI, menu, watcher, hook) calls this.

Archive layout, per root (plans / playbooks), each its own Git repo:
    <root>/<source-relative path>           the document
    <root>/.lasting-plans/docs/<id>.json    its sidecar (identity + metadata + provenance)

Invariants enforced here:
  * a source file disappearing never deletes, untracks or rewrites an archive document;
  * a same-name independent document, or an archive copy edited by hand, is never
    overwritten — both are kept and the conflict is reported;
  * symlinks, hidden entries and anything outside the source root are ignored;
  * only the document and its sidecar are ever staged.
"""
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
import re
import subprocess
import time
import uuid

from . import classify as classify_mod
from . import config as cfgmod
from . import gitrepo, metadata, tools

META_DIR = ".lasting-plans"
DOC_RX = re.compile(r"(\.(md|markdown|txt)(\.[^/]*)?|md)$", re.I)
MAX_BYTES = 5 * 1024 * 1024
SIDECAR_SCHEMA = 1


def settle_seconds():
    return float(os.environ.get("LASTING_PLANS_SETTLE_SECONDS", "2"))


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(path):
    with open(path, "rb") as f:
        return sha256_bytes(f.read())


# ---------------------------------------------------------------- discovery

def is_doc_name(name):
    return not name.startswith(".") and bool(DOC_RX.search(name))


def walk_docs(root):
    """Yield (relpath, abspath) for regular, non-symlink document files under root."""
    root = os.path.realpath(root)
    if not os.path.isdir(root):
        return
    for d, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(x for x in dirs if not x.startswith(".") and not os.path.islink(os.path.join(d, x)))
        for name in sorted(files):
            p = os.path.join(d, name)
            if not is_doc_name(name) or os.path.islink(p) or not os.path.isfile(p):
                continue
            if not os.path.realpath(p).startswith(root + os.sep):
                continue
            yield os.path.relpath(p, root), p


def stable_read(path):
    """Read a file only if it is not being written. Returns bytes, or None to retry later."""
    try:
        a = os.stat(path)
        if a.st_size > MAX_BYTES:
            return None
        if time.time() - a.st_mtime < settle_seconds():
            return None
        with open(path, "rb") as f:
            data = f.read()
        b = os.stat(path)
    except OSError:
        return None
    if (a.st_size, a.st_mtime_ns) != (b.st_size, b.st_mtime_ns) or len(data) != b.st_size:
        return None
    return data


# ---------------------------------------------------------------- sidecars

def sidecar_dir(root):
    return os.path.join(root, META_DIR, "docs")


def sidecar_rel(doc_id):
    return "%s/docs/%s.json" % (META_DIR, doc_id)


def load_sidecars(root):
    out, bad = [], []
    d = sidecar_dir(root)
    if not os.path.isdir(d):
        return out, bad
    for name in sorted(os.listdir(d)):
        if not name.endswith(".json"):
            continue
        p = os.path.join(d, name)
        try:
            with open(p, encoding="utf-8") as f:
                sc = json.load(f)
            if not isinstance(sc, dict) or "id" not in sc or "archive_relpath" not in sc:
                raise ValueError("missing id/archive_relpath")
            out.append(sc)
        except (OSError, ValueError) as e:
            bad.append((p, str(e)))
    return out, bad


def write_sidecar(root, sc):
    cfgmod.atomic_write(os.path.join(root, sidecar_rel(sc["id"])), json.dumps(sc, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- library

class Doc:
    def __init__(self, root_type, root, sc):
        self.type, self.root, self.sc = root_type, root, sc

    @property
    def id(self):
        return self.sc["id"]

    @property
    def path(self):
        return os.path.join(self.root, self.sc["archive_relpath"])

    def as_json(self, source_dir=None):
        d = dict(self.sc)
        d["type"] = self.type
        d["archive_path"] = self.path
        d["archive_present"] = os.path.exists(self.path)
        if source_dir and d.get("source_relpath"):
            d["source_present"] = os.path.exists(os.path.join(source_dir, d["source_relpath"]))
        return d


class Library:
    def __init__(self, cfg=None):
        self.cfg = cfg or cfgmod.load()
        self.source = cfgmod.source_dir(self.cfg)
        self.roots = cfgmod.roots(self.cfg)
        self.docs, self.corrupt = [], []
        self.reload()

    def reload(self):
        self.docs, self.corrupt = [], []
        for t, r in self.roots.items():
            scs, bad = load_sidecars(r)
            self.docs += [Doc(t, r, sc) for sc in scs]
            self.corrupt += bad

    def by_source(self):
        return {d.sc.get("source_relpath"): d for d in self.docs if d.sc.get("source_relpath")}

    def resolve(self, ref):
        """Exact id, id prefix, exact archive/source relpath, or unique path substring."""
        exact = [d for d in self.docs if d.id == ref or d.sc["archive_relpath"] == ref or d.sc.get("source_relpath") == ref]
        if exact:
            return exact
        pref = [d for d in self.docs if d.id.startswith(ref)]
        if pref:
            return pref
        low = ref.lower()
        return [d for d in self.docs if low in d.sc["archive_relpath"].lower()]


# ---------------------------------------------------------------- scan

@contextlib.contextmanager
def scan_lock():
    d = cfgmod.state_dir()
    os.makedirs(d, exist_ok=True)
    f = open(os.path.join(d, "scan.lock"), "w")
    try:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise Busy() from None
        yield
    finally:
        f.close()


class Busy(Exception):
    pass


def _free_relpath(root, rel, taken):
    if rel not in taken and not os.path.exists(os.path.join(root, rel)):
        return rel
    stem, ext = os.path.splitext(rel)
    n = 2
    while True:
        cand = "%s (%d)%s" % (stem, n, ext)
        if cand not in taken and not os.path.exists(os.path.join(root, cand)):
            return cand
        n += 1


def _atomic_copy_bytes(data, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".lp-tmp"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, dest)
    if sha256_file(dest) != sha256_bytes(data):
        raise OSError("hash mismatch after copy to %s" % dest)


def _created_pinned(sc):
    """A creation date set by the user or recovered after a documented loss is never
    overwritten by what the filesystem reports later."""
    s = sc.get("created_source") or ""
    return s == "user" or s.startswith("recovered")


def _record_meta(sc, src_path):
    obs = metadata.observe(src_path)
    sc["modified_utc"] = obs["modified_utc"]
    if not _created_pinned(sc):
        sc["created_utc"] = obs["created_utc"]
        sc["created_source"] = obs["created_source"]
    tags = list(sc.get("tags") or [])
    for t in obs["tags"]:
        if t not in tags:
            tags.append(t)
    sc["tags"] = tags
    if obs.get("finderinfo_hex"):
        sc["finderinfo_hex"] = obs["finderinfo_hex"]
    return obs


def _apply_sidecar_meta(doc_path, sc):
    created = metadata.parse_iso(sc["created_utc"]) if sc.get("created_utc") else None
    modified = metadata.parse_iso(sc["modified_utc"]) if sc.get("modified_utc") else None
    return metadata.apply(doc_path, created_ts=created, modified_ts=modified,
                          tags=sc.get("tags"), finderinfo_hex=sc.get("finderinfo_hex"))


class ScanResult:
    def __init__(self):
        self.events = []    # (kind, doc_id, relpath, detail)
        self.pending = []   # (relpath, reason)
        self.errors = []    # (relpath, reason)

    def add(self, kind, doc_id, rel, detail=""):
        self.events.append((kind, doc_id, rel, detail))

    def as_json(self):
        return {
            "events": [{"kind": k, "id": i, "path": p, "detail": d} for k, i, p, d in self.events],
            "pending": [{"path": p, "reason": r} for p, r in self.pending],
            "errors": [{"path": p, "reason": r} for p, r in self.errors],
        }


def prepare_roots(lib):
    out = {}
    for t, r in lib.roots.items():
        out[t] = gitrepo.ensure_repo(r, t)
    real = [os.path.realpath(r) for r in lib.roots.values()]
    src = os.path.realpath(lib.source)
    for r in real:
        if r == src or r.startswith(src + os.sep) or src.startswith(r + os.sep):
            raise gitrepo.GitError("archive root %s overlaps the swept source %s" % (r, src))
    if real[0] == real[1]:
        raise gitrepo.GitError("plans_root and playbooks_root must differ")
    return out


def _commit(lib, doc_root, rel_doc, doc_id, message, res):
    paths = [rel_doc, sidecar_rel(doc_id)]
    if not gitrepo.has_identity(doc_root):
        res.pending.append((rel_doc, "uncommitted: no Git user.name/user.email configured"))
        return None
    try:
        return gitrepo.commit_paths(doc_root, paths, message)
    except gitrepo.GitError as e:
        res.pending.append((rel_doc, "uncommitted: %s" % e))
        return None


def scan(lib=None):
    """One reconciliation pass. Idempotent: a second run with no changes does nothing."""
    lib = lib or Library()
    res = ScanResult()
    with scan_lock():
        prepare_roots(lib)
        lib.reload()
        _scan_source(lib, res)
        lib.reload()
        _scan_archive_edits(lib, res)
        _sync_folder_tags(lib, res)
        _retry_uncommitted(lib, res)
    _write_last_run(res)
    return res


def _scan_source(lib, res):
    by_src = lib.by_source()
    taken = {t: {d.sc["archive_relpath"] for d in lib.docs if d.type == t} for t in lib.roots}
    present = {rel for rel, _ in walk_docs(lib.source)}
    # docs whose source vanished, keyed by last import hash: candidates for a move/rename
    orphans = {}
    for d in lib.docs:
        s = d.sc.get("source_relpath")
        if s and s not in present:
            orphans.setdefault(d.sc.get("last_import_sha256"), []).append(d)

    for rel, abspath in walk_docs(lib.source):
        data = stable_read(abspath)
        if data is None:
            res.pending.append((rel, "file is changing or too large; will retry"))
            continue
        h = sha256_bytes(data)
        doc = by_src.get(rel)
        if doc is None and orphans.get(h):
            doc = orphans[h].pop(0)
            _handle_move(lib, doc, rel, abspath, res)
            continue
        if doc is None:
            _handle_new(lib, rel, abspath, data, h, taken, res)
            continue
        if h == doc.sc.get("last_import_sha256"):
            _handle_metadata_only(lib, doc, abspath, res)
            continue
        _handle_update(lib, doc, rel, abspath, data, h, taken, res)


def _new_sidecar(rel_src, rel_arch, h, kind, reason, origin="source"):
    return {
        "schema": SIDECAR_SCHEMA,
        "id": uuid.uuid4().hex[:12],
        "origin": origin,
        "source_relpath": rel_src,
        "source_history": [rel_src] if rel_src else [],
        "archive_relpath": rel_arch,
        "type": kind,
        "type_reason": reason,
        "first_seen_utc": now_utc(),
        "last_import_sha256": h,
        "archive_sha256": h,
        "tags": [],
    }


def _handle_new(lib, rel, abspath, data, h, taken, res):
    text = data.decode("utf-8", "replace")
    kind, reason = classify_mod.classify(rel, text, lib.cfg.get("classify_overrides"))
    root = lib.roots[kind]
    arel = _free_relpath(root, rel, taken[kind])
    taken[kind].add(arel)
    sc = _new_sidecar(rel, arel, h, kind, reason)
    try:
        _atomic_copy_bytes(data, os.path.join(root, arel))
    except OSError as e:
        res.errors.append((rel, "copy failed: %s" % e))
        return
    _record_meta(sc, abspath)
    write_sidecar(root, sc)
    failed = _apply_sidecar_meta(os.path.join(root, arel), sc)
    if failed:
        sc["metadata_unapplied"] = failed
        write_sidecar(root, sc)
    note = "" if arel == rel else "renamed to %s (name taken)" % arel
    if _commit(lib, root, arel, sc["id"], "import: %s" % arel, res):
        res.add("imported", sc["id"], arel, (kind + (", " + note if note else "")))


def _handle_move(lib, doc, rel, abspath, res):
    sc = doc.sc
    old_src = sc.get("source_relpath")
    sc["source_relpath"] = rel
    sc.setdefault("source_history", []).append(rel)
    old_arel = sc["archive_relpath"]
    moved = False
    if old_arel == old_src and os.path.exists(doc.path):
        new_arel = _free_relpath(doc.root, rel, {d.sc["archive_relpath"] for d in lib.docs if d.root == doc.root})
        dest = os.path.join(doc.root, new_arel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        os.rename(doc.path, dest)
        sc["archive_relpath"] = new_arel
        moved = True
    write_sidecar(doc.root, sc)
    paths = [old_arel, sc["archive_relpath"]]
    if gitrepo.has_identity(doc.root):
        try:
            gitrepo.commit_paths(doc.root, paths + [sidecar_rel(sc["id"])], "move: %s -> %s" % (old_src, rel))
        except gitrepo.GitError as e:
            res.pending.append((rel, "uncommitted: %s" % e))
            return
    else:
        res.pending.append((rel, "uncommitted: no Git identity"))
        return
    res.add("moved", sc["id"], sc["archive_relpath"], "source %s -> %s%s" % (old_src, rel, "" if moved else " (archive path kept)"))
    _handle_metadata_only(lib, doc, abspath, res)


def _handle_update(lib, doc, rel, abspath, data, h, taken, res):
    sc = doc.sc
    cur = sha256_file(doc.path) if os.path.exists(doc.path) else None
    if cur is None:
        res.pending.append((rel, "archive copy %s was removed by hand; not recreating (see doctor)" % sc["archive_relpath"]))
        return
    if cur != sc.get("last_import_sha256"):
        # the archive copy diverged from what we last imported (a hand edit, committed
        # or not): never overwrite it — keep both
        stem, ext = os.path.splitext(sc["archive_relpath"])
        crel = _free_relpath(doc.root, "%s (source edit %s)%s" % (stem, time.strftime("%Y%m%d-%H%M%S"), ext), taken[doc.type])
        taken[doc.type].add(crel)
        csc = _new_sidecar(None, crel, h, doc.type, "conflict copy", origin="conflict")
        csc["conflict_of"] = sc["id"]
        _atomic_copy_bytes(data, os.path.join(doc.root, crel))
        _record_meta(csc, abspath)
        write_sidecar(doc.root, csc)
        _apply_sidecar_meta(os.path.join(doc.root, crel), csc)
        sc["last_import_sha256"] = h  # do not regenerate the conflict copy every scan
        write_sidecar(doc.root, sc)
        if _commit(lib, doc.root, crel, csc["id"], "conflict: source edit of %s kept as %s" % (sc["archive_relpath"], crel), res):
            gitrepo.commit_paths(doc.root, [sidecar_rel(sc["id"])], "conflict: note on %s" % sc["archive_relpath"])
            res.add("conflict", sc["id"], crel, "archive copy was edited by hand; source version saved alongside")
        return
    _atomic_copy_bytes(data, doc.path)
    sc["last_import_sha256"] = sc["archive_sha256"] = h
    _record_meta(sc, abspath)
    write_sidecar(doc.root, sc)
    _apply_sidecar_meta(doc.path, sc)
    if _commit(lib, doc.root, sc["archive_relpath"], sc["id"], "update: %s" % sc["archive_relpath"], res):
        res.add("updated", sc["id"], sc["archive_relpath"])


def _handle_metadata_only(lib, doc, abspath, res):
    """Source tags newly added (never removed) are unioned into the archive copy."""
    sc = doc.sc
    obs = metadata.observe(abspath)
    new_tags = [t for t in obs["tags"] if t not in (sc.get("tags") or [])]
    if not new_tags:
        return
    sc["tags"] = list(sc.get("tags") or []) + new_tags
    write_sidecar(doc.root, sc)
    if os.path.exists(doc.path):
        metadata.write_tags(doc.path, sc["tags"])
    if gitrepo.has_identity(doc.root):
        try:
            gitrepo.commit_paths(doc.root, [sidecar_rel(sc["id"])], "metadata: tags on %s" % sc["archive_relpath"])
            res.add("metadata", sc["id"], sc["archive_relpath"], "tags + %s" % ", ".join(new_tags))
        except gitrepo.GitError as e:
            res.pending.append((sc["archive_relpath"], "uncommitted: %s" % e))


def _scan_archive_edits(lib, res):
    """Commit hand edits to archive copies, and adopt documents dropped into an archive root."""
    for t, root in lib.roots.items():
        known = {d.sc["archive_relpath"]: d for d in lib.docs if d.root == root}
        for rel, abspath in walk_docs(root):
            if rel.startswith(META_DIR + os.sep):
                continue
            doc = known.get(rel)
            data = stable_read(abspath)
            if data is None:
                if doc is None or sha256_file(abspath) != doc.sc.get("archive_sha256"):
                    res.pending.append((rel, "archive file is changing; will retry"))
                continue
            h = sha256_bytes(data)
            if doc is None:
                kind = t
                sc = _new_sidecar(None, rel, h, kind, "dropped into %s archive" % kind, origin="archive")
                _record_meta(sc, abspath)
                write_sidecar(root, sc)
                if _commit(lib, root, rel, sc["id"], "adopt: %s" % rel, res):
                    res.add("adopted", sc["id"], rel, "file added directly to the archive")
            elif h != doc.sc.get("archive_sha256"):
                doc.sc["archive_sha256"] = h
                doc.sc["modified_utc"] = metadata.utc_iso(os.stat(abspath).st_mtime)
                write_sidecar(root, doc.sc)
                if _commit(lib, root, rel, doc.id, "archive edit: %s" % rel, res):
                    res.add("archive-edit", doc.id, rel)


FOLDERS_REL = META_DIR + "/folders.json"


def load_folder_tags(root):
    try:
        with open(os.path.join(root, FOLDERS_REL), encoding="utf-8") as f:
            d = json.load(f)
        return d.get("tags", {}) if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _sync_folder_tags(lib, res):
    """Finder tags on SOURCE folders are mirrored onto the same folders in each archive
    that has them, and recorded in <root>/.lasting-plans/folders.json so a clone can put
    them back. Additive, like file tags: a tag is never removed from an archive folder."""
    if not metadata.IS_MAC:
        return
    src_tags = {}
    src = os.path.realpath(lib.source)
    for d, dirs, _ in os.walk(src, followlinks=False):
        dirs[:] = sorted(x for x in dirs if not x.startswith(".") and not os.path.islink(os.path.join(d, x)))
        for x in dirs:
            p = os.path.join(d, x)
            t = metadata.read_tags(p)
            if t:
                src_tags[os.path.relpath(p, src)] = t
    for root in lib.roots.values():
        rec = load_folder_tags(root)
        changed = []
        for rel, tags in sorted(src_tags.items()):
            ap = os.path.join(root, rel)
            if not os.path.isdir(ap) or os.path.islink(ap):
                continue  # only folders that hold archived documents exist here
            have = rec.get(rel, [])
            want = have + [t for t in tags if t not in have]
            if want != have:
                rec[rel] = want
                changed.append(rel)
            if not metadata.write_tags(ap, rec[rel]):
                res.pending.append((rel + "/", "could not apply folder tags"))
        if changed:
            cfgmod.atomic_write(os.path.join(root, FOLDERS_REL),
                                json.dumps({"schema": 1, "tags": rec}, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
            if gitrepo.has_identity(root):
                try:
                    gitrepo.commit_paths(root, [FOLDERS_REL], "metadata: folder tags on %s" % ", ".join(changed[:5]))
                    for rel in changed:
                        res.add("metadata", "-", rel + "/", "folder tags " + ", ".join(t.split("\n")[0] for t in rec[rel]))
                except gitrepo.GitError as e:
                    res.pending.append((FOLDERS_REL, "uncommitted: %s" % e))


def apply_folder_tags(root):
    """Re-apply recorded folder tags (after a clone). Returns folders that failed."""
    bad = []
    for rel, tags in load_folder_tags(root).items():
        p = os.path.join(root, rel)
        if os.path.isdir(p) and not metadata.write_tags(p, tags):
            bad.append(rel)
    return bad


def _retry_uncommitted(lib, res):
    """A copy that landed while Git was unavailable is committed on the next pass."""
    for root in lib.roots.values():
        if not gitrepo.has_identity(root):
            continue
        dirty = [p for code, p in gitrepo.status_z(root)]
        mine = {}
        for d in lib.docs:
            if d.root != root:
                continue
            for p in (d.sc["archive_relpath"], sidecar_rel(d.id)):
                if p in dirty:
                    mine.setdefault(d.id, (d, [d.sc["archive_relpath"], sidecar_rel(d.id)]))
        for doc_id, (d, paths) in mine.items():
            if any(e[1] == doc_id for e in res.events):
                continue
            try:
                if gitrepo.commit_paths(root, paths, "catch-up: %s" % d.sc["archive_relpath"]):
                    res.add("committed", doc_id, d.sc["archive_relpath"], "catch-up of an earlier uncommitted copy")
            except gitrepo.GitError as e:
                res.pending.append((d.sc["archive_relpath"], "uncommitted: %s" % e))
    lib.reload()


def _write_last_run(res):
    st = {"finished_utc": now_utc(), "events": len(res.events), "pending": len(res.pending),
          "errors": len(res.errors), "pending_items": res.as_json()["pending"][:50],
          "error_items": res.as_json()["errors"][:50]}
    cfgmod.atomic_write(os.path.join(cfgmod.state_dir(), "last-run.json"), json.dumps(st, indent=2) + "\n")


def last_run():
    try:
        with open(os.path.join(cfgmod.state_dir(), "last-run.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- read paths

def status(lib):
    present = {rel for rel, _ in walk_docs(lib.source)}
    by_src = lib.by_source()
    unprotected = sorted(present - set(by_src))
    counts = {t: sum(1 for d in lib.docs if d.type == t) for t in lib.roots}
    swept = sum(1 for d in lib.docs if d.sc.get("source_relpath") and d.sc["source_relpath"] not in present)
    missing_archive = [d.sc["archive_relpath"] for d in lib.docs if not os.path.exists(d.path)]
    dirty = {}
    for t, r in lib.roots.items():
        if os.path.isdir(os.path.join(r, ".git")):
            dirty[t] = len(gitrepo.status_z(r))
    return {
        "source": lib.source, "roots": lib.roots, "counts": counts,
        "source_files": len(present), "unprotected": unprotected,
        "kept_after_source_gone": swept, "archive_missing": missing_archive,
        "uncommitted_paths": dirty, "corrupt_sidecars": [p for p, _ in lib.corrupt],
        "last_run": last_run(),
    }


def search(lib, query, regex=False, limit=50, context=80):
    rx = re.compile(query if regex else re.escape(query), re.I)
    hits = []
    for d in sorted(lib.docs, key=lambda x: x.sc["archive_relpath"]):
        if not os.path.exists(d.path):
            continue
        with open(d.path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        ms = list(rx.finditer(text))
        name_hit = bool(rx.search(d.sc["archive_relpath"]))
        if not ms and not name_hit:
            continue
        snippets = []
        for m in ms[:3]:
            a, b = max(0, m.start() - context), min(len(text), m.end() + context)
            snippets.append(" ".join(text[a:b].split()))
        hits.append({"id": d.id, "type": d.type, "path": d.sc["archive_relpath"],
                     "matches": len(ms), "name_match": name_hit, "snippets": snippets})
        if len(hits) >= limit:
            break
    return hits


def history(doc):
    rel, scr = doc.sc["archive_relpath"], sidecar_rel(doc.id)
    out = gitrepo.git(doc.root, "log", "--format=\x1e%H\x1f%aI\x1f%s", "--name-only", "--", rel, scr, check=False).stdout
    items = []
    for block in out.split("\x1e")[1:]:
        head, _, files = block.partition("\n")
        sha, date, subj = head.split("\x1f")
        fs = [f for f in files.split("\n") if f]
        kind = "content" if any(f != scr for f in fs) else "metadata"
        items.append({"sha": sha, "date": date, "subject": subj, "kind": kind})
    return items


def diff(doc, rev_a=None, rev_b=None):
    rel = doc.sc["archive_relpath"]
    if rev_a and rev_b:
        args = ["diff", rev_a, rev_b, "--", rel]
    elif rev_a:
        args = ["diff", rev_a, "--", rel]
    else:
        content = [h["sha"] for h in history(doc) if h["kind"] == "content"]
        if len(content) < 2:
            args = ["diff", "HEAD", "--", rel]
        else:
            args = ["diff", content[1], content[0], "--", rel]
    r = gitrepo.git(doc.root, *args, check=False)
    if r.returncode not in (0, 1):
        raise gitrepo.GitError(r.stderr.strip())
    return r.stdout


def set_metadata(doc, created=None, modified=None, add_tags=None):
    sc = doc.sc
    if created:
        sc["created_utc"] = metadata.utc_iso(metadata.parse_iso(created))
        sc["created_source"] = "user"
    if modified:
        sc["modified_utc"] = metadata.utc_iso(metadata.parse_iso(modified))
        sc["modified_source"] = "user"
    for t in add_tags or []:
        sc.setdefault("tags", [])
        if t not in sc["tags"]:
            sc["tags"].append(t)
    write_sidecar(doc.root, sc)
    failed = _apply_sidecar_meta(doc.path, sc) if os.path.exists(doc.path) else ["file missing"]
    sha = None
    if gitrepo.has_identity(doc.root):
        sha = gitrepo.commit_paths(doc.root, [sidecar_rel(doc.id)], "metadata: %s" % sc["archive_relpath"])
    return failed, sha


def type_mismatches(lib):
    """[(doc, new_type, reason)] where today's classifier disagrees with the stored type.
    Reported only; a document changes archive solely through `reclassify`."""
    out = []
    for d in lib.docs:
        if d.sc.get("origin") != "source" or d.sc.get("type_reason") == "reclassified by user":
            continue
        rel = d.sc.get("source_relpath") or d.sc["archive_relpath"]
        if not os.path.exists(d.path):
            continue
        with open(d.path, encoding="utf-8", errors="replace") as f:
            kind, reason = classify_mod.classify(rel, f.read(), lib.cfg.get("classify_overrides"))
        if kind != d.type:
            out.append((d, kind, reason))
    return out


def reclassify(lib, doc, new_type):
    """Move one document (and its sidecar) to the other archive: an add commit in the
    destination, then a removal commit in the origin. Returns (dest_rel, sha_add, sha_rm)."""
    if new_type == doc.type:
        raise ValueError("%s is already a %s" % (doc.sc["archive_relpath"], new_type))
    for r in (doc.root, lib.roots[new_type]):
        if not gitrepo.has_identity(r):
            raise gitrepo.GitError("%s has no Git identity; nothing moved" % r)
    with scan_lock():
        src_root, dst_root = doc.root, lib.roots[new_type]
        old_rel = doc.sc["archive_relpath"]
        taken = {d.sc["archive_relpath"] for d in lib.docs if d.root == dst_root}
        new_rel = _free_relpath(dst_root, old_rel, taken)
        with open(doc.path, "rb") as f:
            data = f.read()
        _atomic_copy_bytes(data, os.path.join(dst_root, new_rel))
        sc = dict(doc.sc)
        sc.update(archive_relpath=new_rel, type=new_type, type_reason="reclassified by user")
        sc.setdefault("type_history", []).append({"from": doc.type, "to": new_type, "at_utc": now_utc()})
        write_sidecar(dst_root, sc)
        _apply_sidecar_meta(os.path.join(dst_root, new_rel), sc)
        sha_add = gitrepo.commit_paths(dst_root, [new_rel, sidecar_rel(sc["id"])],
                                       "reclassify: %s (from %s archive)" % (new_rel, doc.type))
        os.remove(doc.path)
        os.remove(os.path.join(src_root, sidecar_rel(doc.id)))
        sha_rm = gitrepo.commit_paths(src_root, [old_rel, sidecar_rel(doc.id)],
                                      "reclassify: %s moved to the %s archive" % (old_rel, new_type))
    lib.reload()
    return new_rel, sha_add, sha_rm


def apply_metadata(doc):
    """Re-apply recorded dates/tags to the archive file (e.g. after a fresh git clone)."""
    if not os.path.exists(doc.path):
        return ["file missing"]
    return _apply_sidecar_meta(doc.path, doc.sc)


# ---------------------------------------------------------------- reverse import & recovery

def _source_dest_path(lib, doc, force_type=None):
    """Compute the destination path in the source folder for a document.
    For plans, uses source_relpath if available, else archive_relpath.
    For playbooks, only imports if explicitly requested (force_type='playbook')."""
    if doc.type == "playbook" and force_type != "playbook":
        return None, "playbook import requires explicit --force-playbook"

    rel = doc.sc.get("source_relpath") or doc.sc["archive_relpath"]
    dest = os.path.join(lib.source, rel)
    return dest, None


def restore_preview(lib, doc, force_type=None):
    """Dry-run preview of restoring a document to the source folder.
    Returns (can_restore, details_dict) where details_dict has keys:
      - dest_path: destination path
      - source_exists: bool
      - source_sha256: hash if exists
      - archive_sha256: hash of archive copy
      - has_diverged: bool (source differs from last imported)
      - last_common_sha: last known common hash or None
      - conflict: bool (diverged and source exists)"""
    dest, err = _source_dest_path(lib, doc, force_type)
    if err:
        return False, {"error": err}

    source_exists = os.path.exists(dest)
    archive_sha = doc.sc.get("archive_sha256") or (sha256_file(doc.path) if os.path.exists(doc.path) else None)
    last_import = doc.sc.get("last_import_sha256")

    details = {
        "dest_path": dest,
        "source_exists": source_exists,
        "archive_sha256": archive_sha,
        "last_import_sha256": last_import,
        "has_diverged": False,
        "last_common_sha": last_import,
        "conflict": False,
    }

    if source_exists:
        source_sha = sha256_file(dest)
        details["source_sha256"] = source_sha
        if last_import and source_sha != last_import:
            details["has_diverged"] = True
            details["conflict"] = True

    # Can restore if no conflict, or if force_playbook for playbooks
    can = not details["conflict"]
    return can, details


def restore_to_source(lib, doc, force_type=None, apply=False):
    """Restore (copy) a document from archive to source folder.
    If apply=False, only returns preview. If apply=True, copies and returns commit info.
    Returns (preview_or_result, commit_sha_or_None).
    """
    dest, err = _source_dest_path(lib, doc, force_type)
    if err:
        return {"error": err}, None

    can, details = restore_preview(lib, doc, force_type)
    if not can:
        details["error"] = "source has diverged from last import; use --force to overwrite"
        return details, None

    if not apply:
        details["action"] = "preview"
        return details, None

    # Copy archive to source
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(doc.path, "rb") as f:
        data = f.read()
    _atomic_copy_bytes(data, dest)

    # Update sidecar with new import hash
    doc.sc["last_import_sha256"] = sha256_bytes(data)
    doc.sc["source_relpath"] = doc.sc.get("source_relpath") or doc.sc["archive_relpath"]
    if doc.sc.get("source_relpath") not in doc.sc.get("source_history", []):
        doc.sc.setdefault("source_history", []).append(doc.sc["source_relpath"])
    write_sidecar(doc.root, doc.sc)

    # Commit if Git identity exists
    sha = None
    if gitrepo.has_identity(doc.root):
        sha = gitrepo.commit_paths(doc.root, [doc.sc["archive_relpath"], sidecar_rel(doc.id)],
                                   "restore: %s copied to source" % doc.sc["archive_relpath"])

    details["action"] = "restored"
    details["commit"] = sha
    return details, sha


def import_to_source(lib, doc_id, force_type=None):
    """Import a document from archive to source folder (opt-in).
    This is like restore but for documents that may not have a source_relpath.
    Returns (result_dict, commit_sha_or_None)."""
    matches = lib.resolve(doc_id)
    if not matches:
        return {"error": "no document matches %r" % doc_id}, None
    if len(matches) > 1:
        return {"error": "ambiguous: %d matches" % len(matches)}, None
    doc = matches[0]
    return restore_to_source(lib, doc, force_type=force_type, apply=True)


# ---------------------------------------------------------------- doctor (continued)

def doctor(lib):
    checks = []

    def add(name, ok, detail=""):
        checks.append({"check": name, "ok": ok, "detail": detail})

    add("git installed", tools.on_path("git") is not None)
    add("source folder exists", os.path.isdir(lib.source), lib.source)
    for t, r in lib.roots.items():
        is_repo = os.path.isdir(os.path.join(r, ".git"))
        add("%s archive is a Git repo" % t, is_repo, r)
        if is_repo:
            add("%s archive has Git identity" % t, gitrepo.has_identity(r))
    add("sidecars parse", not lib.corrupt, "; ".join("%s: %s" % b for b in lib.corrupt)[:300])
    ids = [d.id for d in lib.docs]
    add("document ids unique", len(ids) == len(set(ids)))
    miss = [d.sc["archive_relpath"] for d in lib.docs if not os.path.exists(d.path)]
    add("every archive document present", not miss, ", ".join(miss[:5]))
    st = status(lib)
    add("every source document protected", not st["unprotected"], "%d unprotected" % len(st["unprotected"]))
    for name, hit, sys_path in tools.shadows():
        checks.append({"check": "PATH: `%s` is %s, not %s (Lasting Plans always uses %s; your shell does not)"
                       % (name, hit, sys_path, sys_path), "ok": True, "detail": "", "note": True})
    mm = type_mismatches(lib)
    add("stored types match the classifier", not mm,
        "; ".join("%s %s -> %s (`lasting-plans reclassify %s %s`)" % (d.id, d.type, k, d.id, k) for d, k, _ in mm[:5]))
    return checks


# ---------------------------------------------------------------- migration

def detect_source_git_repo(source_dir):
    """Check if the source directory is already a Git repo.
    Returns (is_repo, git_dir, has_remote)"""
    git_dir = os.path.join(source_dir, ".git")
    if not os.path.isdir(git_dir):
        return False, None, False
    try:
        remotes = subprocess.run(["git", "-C", source_dir, "remote", "-v"],
                                 capture_output=True, text=True, timeout=10).stdout
        has_remote = bool(remotes.strip())
        return True, git_dir, has_remote
    except Exception:
        return True, git_dir, False


def migrate_existing_git_repo(lib, keep_existing=True):
    """Migration path for users with existing Git repo in Claude's plans folder.
    Performs read-only audit and imports existing working files.
    Does not delete repo or rewrite history.
    Returns (audit_results, imported_count)."""
    is_repo, git_dir, has_remote = detect_source_git_repo(lib.source)
    if not is_repo:
        return {"message": "No existing Git repo in source directory"}, 0

    audit = {
        "source_is_git_repo": True,
        "git_dir": git_dir,
        "has_remote": has_remote,
        "existing_files": [],
        "imported": [],
        "skipped": [],
    }

    # Walk source and find all document files
    for rel, _ in walk_docs(lib.source):
        audit["existing_files"].append(rel)

    # Import each file that's not already in archives
    lib.reload()
    imported = 0
    for rel, abspath in walk_docs(lib.source):
        # Check if already in archive
        by_src = lib.by_source()
        if rel in by_src:
            audit["skipped"].append({"path": rel, "reason": "already in archive"})
            continue

        # Import new file
        data = stable_read(abspath)
        if data is None:
            audit["skipped"].append({"path": rel, "reason": "file changing or too large"})
            continue

        h = sha256_bytes(data)
        # Classify and import using existing scan logic
        text = data.decode("utf-8", "replace")
        kind, reason = classify_mod.classify(rel, text, lib.cfg.get("classify_overrides"))
        root = lib.roots[kind]
        taken = {d.sc["archive_relpath"] for d in lib.docs if d.root == root}
        arel = _free_relpath(root, rel, taken)

        # This mimics _handle_new but for migration
        sc = _new_sidecar(rel, arel, h, kind, reason, origin="migration")
        try:
            _atomic_copy_bytes(data, os.path.join(root, arel))
        except OSError as e:
            audit["skipped"].append({"path": rel, "reason": "copy failed: %s" % e})
            continue
        _record_meta(sc, abspath)
        write_sidecar(root, sc)
        _apply_sidecar_meta(os.path.join(root, arel), sc)
        if _commit(lib, root, arel, sc["id"], "migrate: import %s from existing repo" % arel, None):
            audit["imported"].append({"path": rel, "id": sc["id"], "type": kind})
            imported += 1
        else:
            audit["skipped"].append({"path": rel, "reason": "commit failed"})

    lib.reload()
    return audit, imported


def disaster_recovery_drill(lib):
    """Run a corruption and disaster recovery drill.
    Tests: Git history checkout vs metadata-aware restore, tag appearance.
    Returns results dict."""
    results = {
        "git_checkout_test": False,
        "metadata_restore_test": False,
        "tags_preserved_test": False,
        "errors": [],
    }

    # Test 1: Git checkout restores content
    if not lib.docs:
        results["errors"].append("No documents to test")
        return results

    test_doc = lib.docs[0]

    # Check git history exists
    try:
        history = gitrepo.git(test_doc.root, "log", "--oneline", "--", test_doc.sc["archive_relpath"],
                              check=False).stdout.strip()
        if history:
            results["git_checkout_test"] = True
    except Exception as e:
        results["errors"].append("Git history check failed: %s" % e)

    # Test 2: Metadata restore
    try:
        failed = apply_metadata(test_doc)
        if not failed:
            results["metadata_restore_test"] = True
        else:
            results["errors"].append("Metadata restore failed: %s" % ", ".join(failed))
    except Exception as e:
        results["errors"].append("Metadata restore error: %s" % e)

    # Test 3: Tags preserved
    try:
        if tools.IS_MAC:
            tags = metadata.read_tags(test_doc.path)
            if tags is not None:  # None = error, empty list = no tags
                results["tags_preserved_test"] = True
    except Exception as e:
        results["errors"].append("Tags check error: %s" % e)

    return results


def privacy_secrets_audit(lib):
    """Audit for potential secrets in archived documents.
    Uses redact-secret.py patterns but read-only.
    Returns list of suspicious files."""
    suspicious = []
    patterns = [
        (r"sk-[A-Za-z0-9]{20,}", "OpenAI/Anthropic API key"),
        (r"ghp_[A-Za-z0-9]{36}", "GitHub PAT"),
        (r"gho_[A-Za-z0-9]{36}", "GitHub OAuth token"),
        (r"xoxb-[0-9]{11}-[0-9]{11}-[A-Za-z0-9]{24}", "Slack bot token"),
        (r"xoxp-[0-9]{11}-[0-9]{11}-[0-9]{11}-[A-Za-z0-9]{32}", "Slack user token"),
        (r"AIza[0-9A-Za-z\-_]{35}", "Google API key"),
        (r"ya29\.[0-9A-Za-z\-_]+", "Google OAuth token"),
        (r"password\s*[=:]\s*[^\s]+", "password assignment"),
        (r"secret\s*[=:]\s*[^\s]+", "secret assignment"),
        (r"token\s*[=:]\s*[^\s]+", "token assignment"),
        (r"BEGIN (RSA |EC |DSA )?PRIVATE KEY", "private key"),
    ]

    for d in lib.docs:
        if not os.path.exists(d.path):
            continue
        try:
            with open(d.path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            for pattern, desc in patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    suspicious.append({
                        "id": d.id,
                        "path": d.sc["archive_relpath"],
                        "pattern": desc,
                    })
                    break  # One match per file is enough
        except Exception:
            pass

    return suspicious


# ---------------------------------------------------------------- backup destination

def backup_to_destination(lib, destination, kind=None):
    """Backup archive(s) to a local destination folder (external drive, etc.).
    This creates a mirror of the archive without using Git - just copies files and sidecars.
    If kind is specified ('plan' or 'playbook'), only that archive is backed up.
    Returns (success_count, failed_items)."""
    import shutil

    if not os.path.isdir(destination):
        try:
            os.makedirs(destination, exist_ok=True)
        except OSError as e:
            return 0, [{"error": "cannot create destination: %s" % e}]

    kinds = [kind] if kind in ("plan", "playbook") else list(lib.roots.keys())
    success = 0
    failed = []

    for k in kinds:
        root = lib.roots[k]
        dest_kind = os.path.join(destination, k)
        os.makedirs(dest_kind, exist_ok=True)

        # Copy all documents
        for d in lib.docs:
            if d.type != k:
                continue
            if not os.path.exists(d.path):
                failed.append({"id": d.id, "path": d.sc["archive_relpath"], "error": "source missing"})
                continue
            try:
                dest_path = os.path.join(dest_kind, d.sc["archive_relpath"])
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                shutil.copy2(d.path, dest_path)
                # Also copy sidecar
                sc_src = os.path.join(root, sidecar_rel(d.id))
                sc_dest = os.path.join(dest_kind, sidecar_rel(d.id))
                os.makedirs(os.path.dirname(sc_dest), exist_ok=True)
                shutil.copy2(sc_src, sc_dest)
                success += 1
            except OSError as e:
                failed.append({"id": d.id, "path": d.sc["archive_relpath"], "error": str(e)})

    return success, failed


def find_duplicates(lib, threshold=0.9, min_length=100):
    """Find documents with similar content using content hashing and similarity.
    Returns list of groups of potentially duplicate documents.
    Uses SHA256 for exact matches and simple token overlap for near-duplicates.
    """
    docs_with_content = []
    for d in lib.docs:
        if not os.path.exists(d.path):
            continue
        try:
            with open(d.path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            continue
        if len(content) < min_length:
            continue
        # Normalize: lowercase, strip whitespace, split into words
        tokens = set(content.lower().split())
        if len(tokens) < 10:
            continue
        docs_with_content.append({
            "doc": d,
            "content": content,
            "tokens": tokens,
            "sha256": sha256_bytes(content.encode("utf-8")),
        })

    # First pass: exact SHA matches
    by_sha = {}
    for item in docs_with_content:
        by_sha.setdefault(item["sha256"], []).append(item)

    exact_groups = [items for items in by_sha.values() if len(items) > 1]

    # Second pass: near-duplicate detection using token overlap (Jaccard similarity)
    near_groups = []
    checked = set()
    for i, a in enumerate(docs_with_content):
        for b in docs_with_content[i+1:]:
            key = (a["doc"].id, b["doc"].id)
            if key in checked or (b["doc"].id, a["doc"].id) in checked:
                continue
            checked.add(key)

            # Quick filter: if token counts differ too much, skip
            if abs(len(a["tokens"]) - len(b["tokens"])) / max(len(a["tokens"]), len(b["tokens"])) > 0.5:
                continue

            # Jaccard similarity
            intersection = len(a["tokens"] & b["tokens"])
            union = len(a["tokens"] | b["tokens"])
            if union > 0:
                similarity = intersection / union
                if similarity >= threshold:
                    near_groups.append({
                        "similarity": similarity,
                        "docs": [a, b],
                    })

    return {
        "exact": [
            {
                "count": len(items),
                "sha256": items[0]["sha256"],
                "docs": [{"id": x["doc"].id, "path": x["doc"].sc["archive_relpath"]} for x in items],
            }
            for items in exact_groups
        ],
        "near": sorted(near_groups, key=lambda g: g["similarity"], reverse=True),
    }


# ---------------------------------------------------------------- doctor (continued)
