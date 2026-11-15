"""Bounded classification: filename + first Markdown H1 only, never the body."""
import re

# The word must be the label's HEAD noun: first or last word, never a mid-sentence
# mention ("... plan and playbook preservation" is a plan). Trailing "(v2)" is allowed.
_TAIL = r"\s*(\([^)]*\))?\s*$"
_PLAYBOOK = [
    re.compile(r"^\s*(playbooks?|handbooks?)\b", re.I),
    re.compile(r"\b(playbooks?|handbooks?)" + _TAIL, re.I),
]
# "manual" and "workflow" are also adjectives ("manual-installation-plan", "workflow-fix"),
# so they count only in noun position: "Manual: x", "Workflow — x", "... User Manual",
# "...-workflow.md", "Manual (v4)".
_NOUN_ONLY = [
    re.compile(r"^\s*(manual|workflow)\s*(:|\s[—–-]\s)", re.I),
    re.compile(r"\b(user|operator|operations|reference|owner'?s?)\s+manual\b", re.I),
    re.compile(r"[\s_-](manual|workflow)" + _TAIL, re.I),
    re.compile(r"^\s*(manual|workflow)\s*\(", re.I),
]
_FOLDER = re.compile(r"^_*(playbooks?|handbooks?|workflows?)$", re.I)
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
    for rx in _PLAYBOOK:
        if rx.search(s):
            return "matched playbook/handbook"
    for rx in _NOUN_ONLY:
        if rx.search(s):
            return "matched noun 'manual'/'workflow'"
    return None


def classify(relpath, text, overrides=None):
    """Return (type, reason). type is 'plan' or 'playbook'."""
    if overrides and relpath in overrides:
        return overrides[relpath], "user override"
    for part in relpath.replace("\\", "/").split("/")[:-1]:
        if _FOLDER.match(part):
            return "playbook", "folder %s/" % part
    r = _is_playbook_label(_stem(relpath))
    if r:
        return "playbook", "filename " + r
    r = _is_playbook_label(first_h1(text))
    if r:
        return "playbook", "H1 " + r
    return "plan", "default"
