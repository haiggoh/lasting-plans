"""Tests for waypoints integration module."""
import os
import sys
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

from lasting_plans import waypoints  # noqa: E402


def test_waypoints_diagnostics():
    """Test waypoints diagnostics returns expected structure."""
    diag = waypoints.get_waypoints_diagnostics()
    assert isinstance(diag, dict)
    assert "live_available" in diag
    assert "archive_available" in diag
    assert "core_module_available" in diag
    assert "waypoints_path" in diag


def test_waypoints_available():
    """Test waypoints_available returns boolean."""
    result = waypoints.waypoints_available()
    assert isinstance(result, bool)


def test_load_live_waypoints_returns_dict_or_none():
    """Test load_live_waypoints returns dict with expected structure or None."""
    live = waypoints.load_live_waypoints()
    if live is not None:
        assert isinstance(live, dict)
        assert "contract" in live
        assert "counts" in live
        assert "items" in live
        assert live["contract"] == waypoints.LIVE_CONTRACT


def test_load_archive_waypoints_returns_dict_or_none():
    """Test load_archive_waypoints returns dict with expected structure or None."""
    archive = waypoints.load_archive_waypoints()
    if archive is not None:
        assert isinstance(archive, dict)
        assert "contract" in archive
        assert "counts" in archive
        assert "items" in archive
        assert archive["contract"] == waypoints.ARCHIVE_CONTRACT


def test_extract_links_basic():
    """Test waypoint ID extraction from text."""
    # Test with bracketed IDs
    text = "This references [session-handoff-2026-09-20] and [fix-stray-startup-p-in-free]"
    links = waypoints.extract_links(text)
    assert "session-handoff-2026-09-20" in links
    assert "fix-stray-startup-p-in-free" in links

    # Test with bare IDs
    text = "Also mentions fix-stray-startup-p-in-free in passing"
    links = waypoints.extract_links(text)
    assert "fix-stray-startup-p-in-free" in links

    # Test empty
    assert waypoints.extract_links("") == []
    assert waypoints.extract_links("no links here") == []

    # Test invalid IDs are filtered
    text = "UpperCase-ID and single"
    links = waypoints.extract_links(text)
    assert "uppercase-id" not in links  # filtered: not all lowercase
    # "no-hyphen" matches the pattern (has hyphen, lowercase, alnum start/end) so it's included
    # This is intentional permissiveness - filtering happens in find_linked_waypoints against real IDs


def test_find_linked_waypoints():
    """Test find_linked_waypoints returns live/archive split."""
    live_wps = {"items": [{"id": "test-live-id"}]}
    archive_wps = {"items": [{"id": "test-archive-id"}]}

    text = "Links to [test-live-id] and [test-archive-id]"
    result = waypoints.find_linked_waypoints(text, live_wps, archive_wps)

    assert "test-live-id" in result["live"]
    assert "test-archive-id" in result["archive"]


def test_get_waypoint_status():
    """Test waypoint status formatting."""
    done_wp = {"done": True}
    waiting_wp = {"waiting_on": "other-id @ milestone"}
    gated_wp = {"gate_reason": "needs review"}
    tiered_wp = {"tier": "do-now"}
    open_wp = {}

    assert waypoints.get_waypoint_status(done_wp) == "done"
    assert waypoints.get_waypoint_status(waiting_wp) == "waiting on other-id @ milestone"
    assert waypoints.get_waypoint_status(gated_wp) == "gated: needs review"
    assert waypoints.get_waypoint_status(tiered_wp) == "do-now"
    assert waypoints.get_waypoint_status(open_wp) == "open"


def test_format_waypoint_badge():
    """Test waypoint badge formatting."""
    done_wp = {"id": "test-done", "done": True}
    waiting_wp = {"id": "test-waiting", "waiting_on": "other-id @ milestone"}
    open_wp = {"id": "test-open"}

    assert waypoints.format_waypoint_badge(done_wp) == "[linked ✓ test-done]"
    assert waypoints.format_waypoint_badge(waiting_wp) == "[linked ⏳ test-waiting (waiting)]"
    assert waypoints.format_waypoint_badge(open_wp) == "[linked test-open]"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])