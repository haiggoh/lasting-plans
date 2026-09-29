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
    "plans_root": "~/Claude-plans",
    "playbooks_root": "~/Claude-playbooks",
    "scheduler_enabled": True,
    "interval_seconds": 900,
    "classify_overrides": {},    # source-relative path -> "plan" | "playbook"
}
TYPES = {
    "source_dir": (str, type(None)),
    "plans_root": str,
    "playbooks_root": str,
    "scheduler_enabled": bool,
    "interval_seconds": int,
    "classify_overrides": dict,
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


def load():
    """Defaults overlaid with the user file. Unknown keys are kept, never dropped."""
    cfg = dict(DEFAULTS)
    p = config_path()
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                user = json.load(f)
        except ValueError as e:
            raise ConfigError("malformed config %s: %s" % (p, e)) from e
        if not isinstance(user, dict):
            raise ConfigError("config %s is not a JSON object" % p)
        cfg.update(user)
    for k, t in TYPES.items():
        if not isinstance(cfg.get(k), t):
            raise ConfigError("config key %r has wrong type %s" % (k, type(cfg.get(k)).__name__))
    if cfg["interval_seconds"] < 60:
        raise ConfigError("interval_seconds must be >= 60")
    return cfg


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
    if key == "scheduler_enabled":
        if raw.lower() in ("true", "on", "yes", "1"):
            return True
        if raw.lower() in ("false", "off", "no", "0"):
            return False
        raise ConfigError("expected true/false")
    if key == "interval_seconds":
        try:
            return int(raw)
        except ValueError:
            raise ConfigError("expected an integer") from None
    if key == "source_dir":
        return None if raw in ("", "auto") else raw
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


def roots(cfg):
    return {"plan": expand(cfg["plans_root"]), "playbook": expand(cfg["playbooks_root"])}
