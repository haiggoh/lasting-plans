import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_shortcuts_file_declares_real_executables():
    with open(os.path.join(ROOT, "shortcuts")) as f:
        names = [line.split("#")[0].strip() for line in f if line.split("#")[0].strip()]
    assert names == ["lasting-plans"]
    for name in names:
        target = os.path.join(ROOT, "bin", name)
        assert os.path.isfile(target) and os.access(target, os.X_OK)
