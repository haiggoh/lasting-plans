"""The one place external programs are resolved.

macOS system tools are called by ABSOLUTE path, never looked up on PATH. A same-named
program earlier on PATH is common and silently different: pipx's `xattr` (the Python
package) rejects `-x` and `-w` the way /usr/bin/xattr takes them, so a PATH lookup that
"works" on the developer's machine breaks on a user's, or the reverse. Extended attributes
themselves never go through a program at all: see metadata.py (libc via ctypes).

Tools that legitimately live in user-chosen places (git, gh) are looked up on PATH, and
that lookup happens here too, so tests can enforce that no other module does its own.
"""
import os
import shutil
import sys

IS_MAC = sys.platform == "darwin"

# name -> absolute path. Only these are ever run for these names.
SYSTEM = {
    "launchctl": "/bin/launchctl",
    "SetFile": "/usr/bin/SetFile",   # Xcode Command Line Tools shim
    "xattr": "/usr/bin/xattr",       # not used by the engine; listed so doctor can warn about shadows
}
PATH_TOOLS = ("git", "gh")


def system(name):
    """Absolute path of a macOS system tool, or None if it is not installed there."""
    p = SYSTEM[name]
    return p if os.access(p, os.X_OK) else None


def on_path(name):
    """PATH lookup for tools the user installs where they like (git, gh)."""
    if name not in PATH_TOOLS:
        raise ValueError("%s is a system tool; use tools.system(%r)" % (name, name))
    return shutil.which(name)


def shadows():
    """[(name, path_hit, system_path)] where PATH resolves a system tool's name to a
    different program. Informational: Lasting Plans is unaffected, but the user's own
    shell (and any script they copy from our docs) is not."""
    out = []
    if not IS_MAC:
        return out
    for name, sys_path in SYSTEM.items():
        hit = shutil.which(name)
        if hit and os.path.exists(sys_path) and os.path.realpath(hit) != os.path.realpath(sys_path):
            out.append((name, hit, sys_path))
    return out
