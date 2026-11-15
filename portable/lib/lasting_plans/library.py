"""v0.3 library views over the archives: dates, activity, revisions, historical search, labels.

Three different dates, never conflated:
  created           the sidecar's creation date, with its provenance (may be `unknown`)
  first_seen        when Lasting Plans first imported the document
  last_content_edit the newest commit that changed the document's TEXT
A Git commit date is when the archive recorded a change, not when the file was created,
so it is never offered as a creation date.

Activity counts CONTENT commits only (import, update, archive edit), not scans and not
metadata-only commits.
"""
import datetime
import os
import re

from . import gitrepo, metadata

UNKNOWN = "unknown"


def _git_log(doc, *extra):
    rel = doc.sc["archive_relpath"]
    out = gitrepo.git(doc.root, "log", "--follow", "--format=\x1e%H\x1f%aI\x1f%s", "--name-only",
                      *extra, "--", rel, check=False).stdout
    items = []
    for block in out.split("\x1e")[1:]:
        head, _, files = block.partition("\n")
        sha, date, subj = head.split("\x1f", 2)
        items.append({"sha": sha, "date": date, "subject": subj, "paths": [f for f in files.split("\n") if f]})
    return items


def revisions(doc):
    """Content revisions of one document, newest first: [{n, sha, date, subject}], where
    n counts from 1 (the first imported text). Metadata-only commits are excluded."""
    # a move commit renames the file without changing its text
    revs = [r for r in _git_log(doc) if not r["subject"].startswith("move: ")]
    total = len(revs)
    return [dict(r, n=total - i) for i, r in enumerate(revs)]


def resolve_rev(doc, sel):
    """A revision selector -> commit sha.
       N (1 = first text) | -N (N back from latest; -1 = previous) | latest | first |
       @YYYY-MM-DD (the text as of that day) | a commit sha or prefix."""
    revs = revisions(doc)
    if not revs:
        raise LookupError("no committed revisions")
    s = str(sel).strip()
    if s in ("latest", "0"):
        return revs[0]["sha"]
    if s == "first":
        return revs[-1]["sha"]
    if re.fullmatch(r"-\d+", s):
        k = int(s[1:])
        if k >= len(revs):
            raise LookupError("only %d revision(s); %s goes back too far" % (len(revs), s))
        return revs[k]["sha"]
    if s.isdigit():
        n = int(s)
        for r in revs:
            if r["n"] == n:
                return r["sha"]
        raise LookupError("revision %d does not exist (1..%d)" % (n, len(revs)))
    if s.startswith("@"):
        cutoff = metadata.parse_iso(s[1:]) + (86400 if len(s) == 11 else 0)
        for r in revs:
            if metadata.parse_iso(r["date"]) < cutoff:
                return r["sha"]
        raise LookupError("no revision on or before %s" % s[1:])
    for r in revs:
        if str(r["sha"]).startswith(s):
            return r["sha"]
    raise LookupError("%r is not a revision of this document" % s)


def text_at(doc, sha):
    r = gitrepo.git(doc.root, "show", "%s:%s" % (sha, _path_at(doc, sha)), check=False)
    if r.returncode != 0:
        raise LookupError("cannot read the document at %s" % sha[:10])
    return r.stdout


def _path_at(doc, sha):
    """The document's path in an older commit (it may have moved since)."""
    r = gitrepo.git(doc.root, "show", "--name-only", "--format=", sha, check=False).stdout.split("\n")
    names = [n for n in r if n and not n.startswith(".lasting-plans/")]
    if doc.sc["archive_relpath"] in names or not names:
        return doc.sc["archive_relpath"]
    for p in doc.sc.get("source_history") or []:
        if p in names:
            return p
    return names[0]


def activity(doc, now=None):
    """Distinct dates plus content-update counts for one document."""
    revs = revisions(doc)
    now = now or datetime.datetime.now(datetime.timezone.utc).timestamp()
    first = metadata.parse_iso(revs[-1]["date"]) if revs else None
    days = max(1.0, (now - first) / 86400) if first else None
    return {
        "created": doc.sc.get("created_utc") or UNKNOWN,
        "created_source": doc.sc.get("created_source") or UNKNOWN,
        "first_seen": doc.sc.get("first_seen_utc"),
        "last_content_edit": revs[0]["date"] if revs else None,
        "content_revisions": len(revs),
        "updates": max(0, len(revs) - 1),
        "updates_per_30d": round(max(0, len(revs) - 1) / days * 30, 2) if days else 0.0,
    }


def group_key(doc, by):
    c = doc.sc.get("created_utc")
    if not c:
        return UNKNOWN
    dt = datetime.datetime.fromtimestamp(metadata.parse_iso(c)).astimezone()
    if by == "year":
        return "%04d" % dt.year
    if by == "day":
        return dt.strftime("%Y-%m-%d")
    return dt.strftime("%Y-%m")


def grouped(docs, by="month"):
    """[(key, [docs])], newest group first, `unknown` last."""
    groups = {}
    for d in docs:
        groups.setdefault(group_key(d, by), []).append(d)
    keys = sorted((k for k in groups if k != UNKNOWN), reverse=True) + ([UNKNOWN] if UNKNOWN in groups else [])
    return [(k, sorted(groups[k], key=lambda d: d.sc.get("created_utc") or "", reverse=True)) for k in keys]


def search_history(lib, query, regex=False, limit=50):
    """Find text in ANY committed revision, including text no longer in the current copy.
    [{id, path, commits: [{sha, date, subject}], in_current}]"""
    flag = ["-G", query] if regex else ["-S", query]
    hits = []
    for root in sorted(set(lib.roots.values())):
        if not os.path.isdir(os.path.join(root, ".git")) or not gitrepo.head(root):
            continue
        out = gitrepo.git(root, "log", "-i", *flag, "--format=\x1e%H\x1f%aI\x1f%s", "--name-only", "--", ".",
                          ":(exclude).lasting-plans", check=False).stdout
        by_path = {}
        for block in out.split("\x1e")[1:]:
            head, _, files = block.partition("\n")
            sha, date, subj = head.split("\x1f", 2)
            for f in files.split("\n"):
                if f:
                    by_path.setdefault(f, []).append({"sha": sha, "date": date, "subject": subj})
        docs = {}
        for d in lib.docs:
            if d.root == root:
                for p in [d.sc["archive_relpath"]] + list(d.sc.get("source_history") or []):
                    docs.setdefault(p, d)
        rx = re.compile(query if regex else re.escape(query), re.I)
        seen = set()
        for p, commits in sorted(by_path.items()):
            d = docs.get(p)
            key = d.id if d else p
            if key in seen:
                continue
            seen.add(key)
            cur = False
            if d and os.path.exists(d.path):
                with open(d.path, encoding="utf-8", errors="replace") as f:
                    cur = bool(rx.search(f.read()))
            hits.append({"id": d.id if d else None, "type": d.type if d else None,
                         "path": d.sc["archive_relpath"] if d else p, "commits": commits, "in_current": cur})
            if len(hits) >= limit:
                return hits
    return hits


# ---------------------------------------------------------------- labels

_LABEL_RX = re.compile(r"^[\w][\w .+/-]{0,39}$", re.UNICODE)


def check_label(label):
    label = label.strip()
    if not _LABEL_RX.match(label):
        raise ValueError("label %r: 1-40 letters, digits, space, . + / - _ ; must start with a letter or digit" % label)
    return label


def labels_of(doc):
    return list(doc.sc.get("labels") or [])


def set_labels(doc, add=(), remove=()):
    """Explicit user labels, portable (sidecar only; not Finder tags). Returns the commit."""
    from .engine import sidecar_rel, write_sidecar
    cur = labels_of(doc)
    for label in add:
        label = check_label(label)
        if label not in cur:
            cur.append(label)
    rm = {check_label(x) for x in remove}
    cur = [x for x in cur if x not in rm]
    if cur == labels_of(doc):
        return None
    doc.sc["labels"] = cur
    write_sidecar(doc.root, doc.sc)
    if gitrepo.has_identity(doc.root):
        return gitrepo.commit_paths(doc.root, [sidecar_rel(doc.id)], "labels: %s" % doc.sc["archive_relpath"])
    return None


def all_labels(lib):
    out = {}
    for d in lib.docs:
        for label in labels_of(d):
            out[label] = out.get(label, 0) + 1
    return sorted(out.items(), key=lambda kv: (-kv[1], kv[0].lower()))
