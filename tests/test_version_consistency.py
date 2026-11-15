"""Task 7: version 2.0.0 on every surface — VERSION, plugin.json, __init__.py, CHANGELOG."""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_version_surfaces_agree_and_changelog_has_2_0_0():
    version = open(os.path.join(ROOT, "VERSION"), encoding="utf-8").read().strip()
    assert version == "2.0.0", "VERSION is %s" % version
    plugin = json.load(open(os.path.join(ROOT, ".claude-plugin", "plugin.json"), encoding="utf-8"))
    assert plugin["version"] == version, "plugin.json is %s" % plugin["version"]
    init = open(os.path.join(ROOT, "lib", "lasting_plans", "__init__.py"), encoding="utf-8").read()
    m = re.search(r'__version__\s*=\s*"([^"]+)"', init)
    assert m and m.group(1) == version, "__init__.py __version__ drifted: %s" % (m and m.group(1))
    changelog = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
    assert re.search(r"^## \[2\.0\.0\]", changelog, re.M), "CHANGELOG has no ## [2.0.0] entry"
