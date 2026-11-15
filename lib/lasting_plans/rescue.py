"""Protect plans from Claude Code's 30-day cleanup — before it deletes, and after.

Measured facts (2026-11-15): the sweep deletes by MTIME at session start (~daily,
~/.claude/.last-cleanup) and touches TOP-LEVEL files only. Known bugs (anthropics/
claude-code#45903, pinned old SDKs dropping cleanupPeriodDays) make it use the 30-day
default even when more is configured, so the protected period is min(configured, 30).

`move_before_cleanup` acts BEFORE the sweep (os.rename within one volume keeps the
inode, so birthtime/mtime/Finder tags all survive untouched); `put_back` is the
safety net AFTER a deletion, restoring from the archive INTO <cleanup_rescue_subdir>/
(never _ARCHIVED/ — being saved is not being done). Every put-back re-applies the
sidecar's dates/tags and verifies by re-reading.
"""
import json
import os

from . import config as cfgmod
from . import engine, gitrepo, metadata

MARGIN_DAYS = 2


def _trash_dir():
    return os.environ.get("LASTING_PLANS_TRASH_DIR") or os.path.join(cfgmod.home(), ".Trash")


def in_trash(sha):
    """True if a file with this sha256 sits in the Trash. PermissionError (launchd's
    TCC context cannot read ~/.Trash) propagates — the caller defers instead."""
    def _raise(e):
        raise e
    for r, _dirs, files in os.walk(_trash_dir(), onerror=_raise):
        for f in files:
            p = os.path.join(r, f)
            try:
                if os.path.getsize(p) <= engine.MAX_BYTES and engine.sha256_file(p) == sha:
                    return True
            except OSError:
                continue
    return False


def cleanup_period_days():
    """cleanupPeriodDays from Claude Code settings (same resolution as config.source_dir)."""
    claude = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(cfgmod.home(), ".claude")
    try:
        with open(os.path.join(claude, "settings.json"), encoding="utf-8") as f:
            v = json.load(f).get("cleanupPeriodDays")
        if isinstance(v, int) and v > 0:
            return v
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return 30


def effective_period_days():
    """min(configured, 30) — the known bugs make the sweep use 30 even when more is set."""
    return min(cleanup_period_days(), 30)


def rescue_subdir(cfg):
    return cfg.get("cleanup_rescue_subdir") or "_SAVED-FROM-CLEANUP"


def at_risk(lib, now):
    """Top-level source docs whose CURRENT mtime age >= effective_period_days - MARGIN_DAYS,
    excluding any that sorting.is_complete would send to _ARCHIVED/ (sorting runs first)."""
    threshold = (effective_period_days() - MARGIN_DAYS) * 86400
    out = []
    from . import sorting
    by_src = lib.by_source()
    for rel, abspath in engine.walk_docs(lib.source):
        if "/" in rel:
            continue
        if now - os.stat(abspath).st_mtime < threshold:
            continue
        doc = by_src.get(rel)
        if doc is not None:
            text = engine.stable_read(abspath)
            if text is not None:
                ok, _why = sorting.is_complete(lib, doc, text.decode("utf-8", "replace"), now)
                if ok:
                    continue    # finished plans go to _ARCHIVED/ via sorting, not here
        out.append(rel)
    return sorted(out)


def move_before_cleanup(lib, rel):
    """Move the source doc into <cleanup_rescue_subdir>/ via sorting.source_move (the one
    helper; os.rename keeps the inode ⇒ all metadata survives), then verify. Returns
    the new source relpath."""
    from . import sorting
    cfg = lib.cfg
    sub = rescue_subdir(cfg)
    src = lib.source
    old_abs = os.path.join(src, rel)
    before = metadata.observe(old_abs)
    base = os.path.basename(rel)
    taken = {r for r, _ in engine.walk_docs(src)}
    new_rel = engine._free_relpath(src, sub + "/" + base, taken)
    sorting.source_move(lib, rel, new_rel,
                        "Lasting Plans: moved %s out of reach of Claude Code's 30-day cleanup" % base,
                        force=True)
    after = metadata.observe(os.path.join(src, new_rel))
    assert (before["created_utc"], before["modified_utc"], before["tags"]) == \
           (after["created_utc"], after["modified_utc"], after["tags"]), "metadata lost on rename"
    return new_rel


def looks_like_cleanup(lib, doc, now):
    """True when a vanished top-level source doc was almost certainly taken by the
    cleanup: top-level path, last recorded source mtime older than cleanup_period_days,
    not in the Trash, not marked deleted_by the user."""
    s = doc.sc.get("source_relpath")
    if not s or "/" in s:
        return False, "not top-level"
    if doc.sc.get("deleted_by") == "user":
        return False, "marked deleted by the user"
    mod = metadata.parse_iso(doc.sc.get("modified_utc") or "")
    if not mod or (now - mod) <= effective_period_days() * 86400:
        return False, "too recent for the cleanup"
    sha = doc.sc.get("archive_sha256")
    if sha:
        try:
            if in_trash(sha):
                return False, "same content is in the Trash — the user deleted it"
        except PermissionError:
            return False, "deferred: Trash unreadable here"
    return True, "top-level, older than the cleanup period, not trashed"


def put_back(lib, doc):
    """Copy the archive bytes back into <source>/<cleanup_rescue_subdir>/<name>,
    re-apply the sidecar's dates/tags and verify, commit as a move. Returns the new
    source relpath."""
    cfg = lib.cfg
    sub = rescue_subdir(cfg)
    src = lib.source
    old_rel = doc.sc.get("source_relpath") or doc.sc["archive_relpath"]
    base = os.path.basename(old_rel)
    taken = {r for r, _ in engine.walk_docs(src)}
    new_rel = engine._free_relpath(src, sub + "/" + base, taken)
    new_abs = os.path.join(src, new_rel)
    os.makedirs(os.path.dirname(new_abs), exist_ok=True)
    with open(doc.path, "rb") as f:
        data = f.read()
    engine._atomic_copy_bytes(data, new_abs)
    failed = engine._apply_sidecar_meta(new_abs, doc.sc)
    obs = metadata.observe(new_abs)
    mism = []
    if failed:
        mism += failed
    if doc.sc.get("modified_utc") and obs["modified_utc"] and \
            abs(metadata.parse_iso(doc.sc["modified_utc"]) - metadata.parse_iso(obs["modified_utc"])) > 2:
        mism.append("mtime")
    if mism:
        doc.sc["metadata_unapplied"] = mism
        engine.write_sidecar(lib.root, doc.sc)
    doc.sc["source_relpath"] = new_rel
    if new_rel not in doc.sc.get("source_history", []):
        doc.sc.setdefault("source_history", []).append(new_rel)
    engine.write_sidecar(lib.root, doc.sc)
    if gitrepo.toplevel(src) == os.path.realpath(src):
        from . import sorting
        sorting.commit_source_move(src, old_rel, new_rel,
                                   "Lasting Plans: kept %s (removed by Claude Code's 30-day cleanup)" % base)
    return new_rel
