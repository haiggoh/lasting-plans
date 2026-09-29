"""Bounded classification: filename + first Markdown H1 only, never the body."""
import re

_PLAYBOOK = re.compile(r"\b(playbooks?|handbooks?)\b", re.I)
# "manual" only as a noun: "Manual: ...", "... User Manual", "...-manual.md", "Manual (v4)".
_MANUAL = [
    re.compile(r"^\s*manual\s*(:|\s[—–-]\s)", re.I),  # "Manual: x" / "Manual — x", not "manual-installation"
    re.compile(r"\b(user|operator|operations|reference|owner'?s?)\s+manual\b", re.I),
    re.compile(r"[\s_-]manual\s*$", re.I),
    re.compile(r"\bmanual\s*\(", re.I),
]
H1_SCAN_LINES = 40


def first_h1(text):
    lines = text.splitlines()[:200]
    i = 0
    if lines and lines[0].strip() == "---":
        for j in range(1, len(lines)):
            if lines[j].strip() in ("---", "..."):
                i = j + 1
                break
    for line in lines[i:i + H1_SCAN_LINES]:
        m = re.match(r"^#\s+(.+?)\s*#*\s*$", line)
        if m:
            return m.group(1)
    return ""


def _stem(name):
    base = name.rsplit("/", 1)[-1]
    return re.sub(r"\.(md|markdown|txt)$", "", base, flags=re.I)


def _is_playbook_label(s):
    s = s.replace("_", " ")
    if _PLAYBOOK.search(s):
        return "matched playbook/handbook"
    for rx in _MANUAL:
        if rx.search(s):
            return "matched noun 'manual'"
    return None


def classify(relpath, text, overrides=None):
    """Return (type, reason). type is 'plan' or 'playbook'."""
    if overrides and relpath in overrides:
        return overrides[relpath], "user override"
    r = _is_playbook_label(_stem(relpath))
    if r:
        return "playbook", "filename " + r
    r = _is_playbook_label(first_h1(text))
    if r:
        return "playbook", "H1 " + r
    return "plan", "default"
