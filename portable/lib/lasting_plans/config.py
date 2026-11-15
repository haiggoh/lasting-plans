"""User-owned settings and state, kept outside the plugin cache.

Config:  $LASTING_PLANS_CONFIG_DIR or ~/.config/lasting-plans/config.json
State:   $LASTING_PLANS_STATE_DIR  or ~/.local/state/lasting-plans/
"""
import json
import os
import tempfile

DEFAULTS = {
    "schema": 1,
    "source_dir": None,          # None = discover from CLAUDE_CONFIG_DIR / settings.json
    "archive_root": "~/Claude-plans",   # THE archive; its paths mirror the source layout
    "remote": None,              # single private Git URL or None (= local only)
    "layout": 1,                 # 1 = v1 two-archive layout (migration pending), 2 = migrated
    "retired_archives": [],      # v1 roots kept (moved/symlinked) by the migration, never read
    "auto_repair": True,         # background repair on watcher/hook passes
    "alert_after_hours": 24,     # a problem must persist this long before the banner mentions it (min 1)
    "alert_min_attempts": 3,     # …and be attempted this often (min 1)
    "archive_deletions": "restore-unless-trashed",  # restore | restore-unless-trashed | honor
    "auto_sort": True,           # move completed plans to archive_subdir, playbooks to playbooks_subdir
    "archive_subdir": "_ARCHIVED",
    "playbooks_subdir": "_PLAYBOOKS",
    "cleanup_rescue_subdir": "_SAVED-FROM-CLEANUP",
    "cleanup_protection": "before",  # before | after | off — against Claude Code's 30-day cleanup
    "complete_quiet_days": 3,    # days a finished-looking plan waits before it is archived (min 0)
    "scheduler_enabled": True,
    "interval_seconds": 900,
    "classify_overrides": {},    # source-relative path -> "plan" | "playbook"
    "remotes": {},               # legacy v1 container; `remotes.plan` resolves to `remote`
    "remote_push": "auto",       # "auto": push after each committing scan; "manual": only on `remote push`
    "saved_searches": {},        # name -> {query, regex, type, labels, history}
}
TYPES = {
    "source_dir": (str, type(None)),
    "archive_root": str,
    "remote": (str, type(None)),
    "layout": int,
    "retired_archives": list,
    "auto_repair": bool,
    "alert_after_hours": int,
    "alert_min_attempts": int,
    "archive_deletions": str,
    "auto_sort": bool,
    "archive_subdir": str,
    "playbooks_subdir": str,
    "cleanup_rescue_subdir": str,
    "cleanup_protection": str,
    "complete_quiet_days": int,
    "scheduler_enabled": bool,
    "interval_seconds": int,
    "classify_overrides": dict,
    "remotes": dict,
    "remote_push": str,
    "saved_searches": dict,
}


def home():
    return os.path.expanduser("~")


def config_dir():
    return os.environ.get("LASTING_PLANS_CONFIG_DIR") or os.path.join(home(), ".config", "lasting-plans")


def state_dir():
    return os.environ.get("LASTING_PLANS_STATE_DIR") or os.path.join(home(), ".local", "state", "lasting-plans")


def config_path():
    return os.path.join(config_dir(), "config.json")


class ConfigError(Exception):
    pass


# The single source for each user-facing behaviour: (key, label, choices, explanation).
# choices: ["on","off"] for a toggle, [("value","description"), ...] for a choice row,
# ["int"] for an integer. `settings show` and the `behaviour` menu both read this table.
BEHAVIOUR_SETTINGS = [
    ("auto_repair", "Fix problems automatically in the background", ["on", "off"],
     "off: the banner lists pending items again, as before 2.0."),
    ("archive_deletions", "When a document vanishes from the backup",
     [("restore-unless-trashed", "restore it, unless you put it in the Trash"),
      ("restore", "always restore it"),
      ("honor", "leave it deleted (Git keeps it)")], ""),
    ("auto_sort", "Sort plans into folders", ["on", "off"],
     "moves completed plans to _ARCHIVED/ and playbooks to _PLAYBOOKS/. Moves only, never deletes "
     "anything. Not related to Claude Code's 30-day cleanup, which this plugin protects you from."),
    ("cleanup_protection", "Protect plans from Claude Code's 30-day cleanup",
     [("before", "move plans into _SAVED-FROM-CLEANUP/ shortly before the cleanup would delete them (dates and colour labels kept)"),
      ("after", "only put them back there after the cleanup deleted them"),
      ("off", "leave them; they stay only in the backup")], ""),
    ("complete_quiet_days", "Days a finished-looking plan waits before it is archived", ["int"], ""),
    ("alert_after_hours", "Hours a problem must persist before the banner mentions it", ["int"], ""),
]

BEHAVIOUR_LABELS = {key: label for key, label, _c, _e in BEHAVIOUR_SETTINGS}


def validate(cfg):
    """Raise ConfigError on any invalid value. Called by load() and by every write path."""
    for k, t in TYPES.items():
        if not isinstance(cfg.get(k), t):
            raise ConfigError("config key %r has wrong type %s" % (k, type(cfg.get(k)).__name__))
    if cfg["remote_push"] not in ("auto", "manual"):
        raise ConfigError("remote_push must be auto or manual")
    if set(cfg["remotes"]) - {"plan", "playbook"}:
        raise ConfigError("remotes keys must be plan/playbook")
    if cfg["interval_seconds"] < 60:
        raise ConfigError("interval_seconds must be >= 60")
    if cfg["alert_after_hours"] < 1:
        raise ConfigError("alert_after_hours must be >= 1")
    if cfg["alert_min_attempts"] < 1:
        raise ConfigError("alert_min_attempts must be >= 1")
    if cfg["complete_quiet_days"] < 0:
        raise ConfigError("complete_quiet_days must be >= 0")
    if cfg["archive_deletions"] not in ("restore-unless-trashed", "restore", "honor"):
        raise ConfigError("archive_deletions must be restore-unless-trashed, restore or honor")
    if cfg["cleanup_protection"] not in ("before", "after", "off"):
        raise ConfigError("cleanup_protection must be before, after or off")
    return cfg


def load():
    """Defaults overlaid with the user file. Unknown keys are kept, never dropped."""
    cfg = dict(DEFAULTS)
    p = config_path()
    user = {}
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                user = json.load(f)
        except ValueError as e:
            raise ConfigError("malformed config %s: %s" % (p, e)) from e
        if not isinstance(user, dict):
            raise ConfigError("config %s is not a JSON object" % p)
        cfg.update(user)
    # Legacy v1 keys resolve to the 2.0.0 names (read-compatible; the layout
    # migration is what writes the new keys into the file).
    if "archive_root" not in user and isinstance(user.get("plans_root"), str):
        cfg["archive_root"] = user["plans_root"]
    if "retired_archives" not in user and isinstance(user.get("playbooks_root"), str):
        cfg["retired_archives"] = [user["playbooks_root"]]
    if cfg.get("remote") is None and isinstance((cfg.get("remotes") or {}).get("plan"), str):
        cfg["remote"] = cfg["remotes"]["plan"]
    return validate(cfg)


def atomic_write(path, text, mode=0o644):
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if os.path.exists(path):
            mode = os.stat(path).st_mode & 0o777
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def save(cfg):
    p = config_path()
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            old = f.read()
        atomic_write(p + ".bak", old)
    atomic_write(p, json.dumps(cfg, indent=2, sort_keys=True) + "\n")


def parse_value(key, raw):
    if key not in TYPES:
        raise ConfigError("unknown key %r (known: %s)" % (key, ", ".join(sorted(TYPES))))
    if key in ("scheduler_enabled", "auto_repair", "auto_sort"):
        if raw.lower() in ("true", "on", "yes", "1"):
            return True
        if raw.lower() in ("false", "off", "no", "0"):
            return False
        raise ConfigError("expected true/false")
    if key in ("interval_seconds", "alert_after_hours", "alert_min_attempts", "complete_quiet_days", "layout"):
        try:
            return int(raw)
        except ValueError:
            raise ConfigError("expected an integer") from None
    if key in ("archive_deletions", "cleanup_protection"):
        choices = ("restore-unless-trashed", "restore", "honor") if key == "archive_deletions" else ("before", "after", "off")
        if raw not in choices:
            raise ConfigError("expected one of %s" % ", ".join(choices))
        return raw
    if key == "source_dir":
        return None if raw in ("", "auto") else raw
    if key == "remote":
        return None if raw in ("", "none", "off") else raw
    if key == "layout":
        try:
            return int(raw)
        except ValueError:
            raise ConfigError("expected an integer") from None
    if key == "retired_archives":
        try:
            v = json.loads(raw)
        except ValueError as e:
            raise ConfigError("expected a JSON array: %s" % e) from e
        if not isinstance(v, list):
            raise ConfigError("expected a JSON array")
        return v
    if key == "remotes":
        raise ConfigError("use `lasting-plans remote set plan|playbook URL` (it checks privacy first)")
    if key == "classify_overrides":
        try:
            v = json.loads(raw)
        except ValueError as e:
            raise ConfigError("expected JSON object: %s" % e) from e
        return v
    return raw


def expand(p):
    return os.path.abspath(os.path.expanduser(p))


def source_dir(cfg):
    """The Claude Code plans folder: explicit setting, else plansDirectory, else <config>/plans."""
    if cfg.get("source_dir"):
        return expand(cfg["source_dir"])
    claude = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(home(), ".claude")
    try:
        with open(os.path.join(claude, "settings.json"), encoding="utf-8") as f:
            pd = json.load(f).get("plansDirectory")
        if isinstance(pd, str) and pd:
            return expand(pd)
    except (OSError, ValueError):
        pass
    return os.path.join(expand(claude), "plans")


def archive_root(cfg):
    """THE one archive; every document sits at its source-relative path inside it."""
    return expand(cfg["archive_root"])
