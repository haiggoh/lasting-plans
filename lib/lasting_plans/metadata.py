"""Filesystem metadata that Git cannot carry: birth time and Finder tags.

Read and write are best-effort and report what they could not do; nothing here
invents a value. Tag writes are additive (union), so a user's existing tags survive.
"""
import datetime
import os
import plistlib
import subprocess
import sys

from . import tools

TAGS_ATTR = "com.apple.metadata:_kMDItemUserTags"
FINDERINFO_ATTR = "com.apple.FinderInfo"
IS_MAC = sys.platform == "darwin"


def utc_iso(ts):
    if ts is None:
        return None
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# 1984-01-24 00:00 local time (the Macintosh launch date) is what Finder/HFS tools write
# when a file has no creation date; stored as-is it would read as a real, very old date.
_SENTINEL_DAY = datetime.date(1984, 1, 24)


def is_no_birthtime_sentinel(ts):
    if ts is None or ts <= 0:
        return ts is not None
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).date() in (
        _SENTINEL_DAY - datetime.timedelta(days=1), _SENTINEL_DAY)


def parse_iso(s):
    s = s.strip().replace("Z", "+00:00")
    if len(s) == 10:
        s += "T00:00:00+00:00"
    dt = datetime.datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.astimezone()  # naive input = local time
    return dt.timestamp()


_libc = None


def _lib():
    """libc getxattr/setxattr via ctypes: no subprocess, immune to a foreign `xattr` on PATH."""
    global _libc
    if _libc is None and IS_MAC:
        import ctypes
        import ctypes.util
        lib = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        lib.getxattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
        lib.getxattr.restype = ctypes.c_ssize_t
        lib.setxattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
        lib.setxattr.restype = ctypes.c_int
        _libc = lib
    return _libc


XATTR_NOFOLLOW = 0x0001


def read_raw_xattr(path, name):
    lib = _lib()
    if lib is None:
        return None
    import ctypes
    p, n = os.fsencode(path), name.encode()
    size = lib.getxattr(p, n, None, 0, 0, XATTR_NOFOLLOW)
    if size <= 0:
        return None
    buf = ctypes.create_string_buffer(size)
    got = lib.getxattr(p, n, buf, size, 0, XATTR_NOFOLLOW)
    return buf.raw[:got] if got > 0 else None


def write_raw_xattr(path, name, data):
    lib = _lib()
    if lib is None:
        return False
    return lib.setxattr(os.fsencode(path), name.encode(), data, len(data), 0, XATTR_NOFOLLOW) == 0


def remove_raw_xattr(path, name):
    lib = _lib()
    if lib is None:
        return False
    if not hasattr(lib, "_rm_ready"):
        import ctypes
        lib.removexattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
        lib.removexattr.restype = ctypes.c_int
        lib._rm_ready = True
    return lib.removexattr(os.fsencode(path), name.encode(), XATTR_NOFOLLOW) == 0


def read_tags(path):
    raw = read_raw_xattr(path, TAGS_ATTR)
    if not raw:
        return []
    try:
        v = plistlib.loads(raw)
    except Exception:
        return []
    return [t for t in v if isinstance(t, str)] if isinstance(v, list) else []


def write_tags(path, tags):
    """Union `tags` into the file's existing tags. Returns True if the result holds all of them."""
    if not IS_MAC:
        return False
    have = read_tags(path)
    want = list(have)
    for t in tags:
        if t not in want:
            want.append(t)
    if want == have:
        return True
    ok = write_raw_xattr(path, TAGS_ATTR, plistlib.dumps(want, fmt=plistlib.FMT_BINARY))
    return ok and all(t in read_tags(path) for t in tags)


def observe(path):
    """Snapshot of what the filesystem can tell us, with provenance."""
    st = os.stat(path)
    birth = getattr(st, "st_birthtime", None)
    source = "filesystem birthtime"
    if birth is None:
        source = "unknown"
    elif is_no_birthtime_sentinel(birth):
        birth, source = None, "unknown (filesystem reports the 1984-01-24 no-date placeholder)"
    snap = {
        "modified_utc": utc_iso(st.st_mtime),
        "created_utc": utc_iso(birth),
        "created_source": source,
        "tags": read_tags(path) if IS_MAC else [],
        "tags_source": "finder xattr" if IS_MAC else "unsupported on this platform",
    }
    fi = read_raw_xattr(path, FINDERINFO_ATTR) if IS_MAC else None
    if fi and any(fi):
        snap["finderinfo_hex"] = fi.hex()
    return snap


def set_birthtime(path, ts):
    """macOS only, via SetFile (Xcode CLT). Returns True only if a re-read confirms it."""
    setfile = tools.system("SetFile") if IS_MAC else None
    if not setfile:
        return False
    stamp = datetime.datetime.fromtimestamp(ts).strftime("%m/%d/%Y %H:%M:%S")
    try:
        r = subprocess.run([setfile, "-d", stamp, path], capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    if r.returncode != 0:
        return False
    return abs(getattr(os.stat(path), "st_birthtime", -1) - int(ts)) <= 1


def apply(path, created_ts=None, modified_ts=None, tags=None, finderinfo_hex=None):
    """Apply metadata to an archive file. Returns the list of fields that could NOT be applied.

    Order matters: SetFile and xattr writes can bump nothing, but set mtime last anyway,
    and birthtime cannot be later than mtime on APFS (it would be clamped).
    """
    failed = []
    if tags:
        if not write_tags(path, tags):
            failed.append("tags")
    if finderinfo_hex and IS_MAC and not read_raw_xattr(path, FINDERINFO_ATTR):
        if not write_raw_xattr(path, FINDERINFO_ATTR, bytes.fromhex(finderinfo_hex)):
            failed.append("finderinfo")
    if created_ts is not None:
        if not set_birthtime(path, created_ts):
            failed.append("created")
    if modified_ts is not None:
        st = os.stat(path)
        os.utime(path, (st.st_atime, modified_ts))
    return failed
