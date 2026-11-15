"""Task 7: version 2.0.0 on every surface — VERSION, plugin.json, __init__.py, CHANGELOG."""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_version_surfaces_agree_and_changelog_top_entry_matches():
    version = open(os.path.join(ROOT, "VERSION"), encoding="utf-8").read().strip()
    plugin = json.load(open(os.path.join(ROOT, ".claude-plugin", "plugin.json"), encoding="utf-8"))
    assert plugin["version"] == version, "plugin.json is %s" % plugin["version"]
    init = open(os.path.join(ROOT, "lib", "lasting_plans", "__init__.py"), encoding="utf-8").read()
    m = re.search(r'__version__\s*=\s*"([^"]+)"', init)
    assert m and m.group(1) == version, "__init__.py __version__ drifted: %s" % (m and m.group(1))
    changelog = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
    top = re.search(r"^## \[([^\]]+)\]", changelog, re.M)
    assert top and top.group(1) == version, "CHANGELOG top entry is %s, VERSION is %s" % (top and top.group(1), version)
