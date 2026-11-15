"""Waypoints integration — read waypoints store and link to archived documents.

Uses the documented public core module: `waypoints_core.load_store()` and `waypoints_core.load_archive()`.
Contract version 3 (live) / 1 (archive).
"""

import os
import re
import sys
from typing import Optional

# Add waypoints checkout to path for direct core module access
_WAYPOINTS_PATH = os.path.expanduser("~/ClaudeWorkspace/waypoints")
if os.path.isdir(_WAYPOINTS_PATH):
    sys.path.insert(0, _WAYPOINTS_PATH)

try:
    import waypoints_core as wp
    WAYPOINTS_AVAILABLE = True
except ImportError:
    WAYPOINTS_AVAILABLE = False
    wp = None


LIVE_CONTRACT = 3
ARCHIVE_CONTRACT = 1


def load_live_waypoints() -> Optional[dict]:
    """Load live waypoints using waypoints_core.load_store() and list_payload(). Returns None if unavailable."""
    if not WAYPOINTS_AVAILABLE:
        return None
    try:
        store = wp.load_store()
        items = store.get("items", [])
        return wp.list_payload(items)
    except Exception:
        return None


def load_archive_waypoints() -> Optional[dict]:
    """Load archived waypoints using waypoints_core.load_archive() and archive_payload(). Returns None if unavailable."""
    if not WAYPOINTS_AVAILABLE:
        return None
    try:
        archive = wp.load_archive()
        items = archive.get("items", [])
        return wp.archive_payload(items)
    except Exception:
        return None


def extract_links(text: str) -> list[str]:
    """Extract explicit waypoint IDs from text. Matches [id] or bare id patterns in titles/summaries."""
    if not text:
        return []
    # Match [waypoint-id] or waypoint-id where id matches the waypoint slug pattern
    # Waypoint IDs are typically kebab-case with optional numbers
    pattern = r'(?:\[|\b)([a-z0-9][a-z0-9-]{2,}[a-z0-9])(?:\]|\b)'
    matches = re.findall(pattern, text, re.IGNORECASE)
    # Filter to plausible waypoint IDs (lowercase, kebab-case, at least one hyphen)
    return [m for m in matches if m.islower() and '-' in m]


def find_linked_waypoints(doc_text: str, live_wps: dict = None, archive_wps: dict = None) -> dict:
    """Find waypoints explicitly linked in a document's text.
    Returns dict with 'live' and 'archive' lists of matched waypoint IDs.
    """
    linked_ids = extract_links(doc_text)
    result = {"live": [], "archive": []}

    if live_wps and "items" in live_wps:
        live_ids = {item["id"] for item in live_wps["items"]}
        result["live"] = [wp_id for wp_id in linked_ids if wp_id in live_ids]

    if archive_wps and "items" in archive_wps:
        archive_ids = {item["id"] for item in archive_wps["items"]}
        result["archive"] = [wp_id for wp_id in linked_ids if wp_id in archive_ids]

    return result


def get_waypoint_status(wp_item: dict) -> str:
    """Get a human-readable status for a waypoint item."""
    if wp_item.get("done"):
        return "done"
    if wp_item.get("waiting_on"):
        return f"waiting on {wp_item['waiting_on']}"
    if wp_item.get("gate_reason"):
        return f"gated: {wp_item['gate_reason']}"
    if wp_item.get("tier"):
        return f"{wp_item['tier']}"
    return "open"


def format_waypoint_badge(wp_item: dict) -> str:
    """Format a waypoint as a display badge with status indicator."""
    if wp_item.get("done"):
        return f"[linked ✓ {wp_item['id']}]"
    if wp_item.get("waiting_on"):
        return f"[linked ⏳ {wp_item['id']} (waiting)]"
    return f"[linked {wp_item['id']}]"


def get_linked_waypoints_for_doc(doc, live_wps: dict = None, archive_wps: dict = None) -> dict:
    """Get linked waypoints for a document, returning full waypoint objects."""
    if not live_wps and not archive_wps:
        live_wps = load_live_waypoints()
        archive_wps = load_archive_waypoints()

    if not doc.path or not os.path.exists(doc.path):
        return {"live": [], "archive": []}

    try:
        with open(doc.path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return {"live": [], "archive": []}

    linked_ids = find_linked_waypoints(text, live_wps, archive_wps)

    result = {"live": [], "archive": []}

    if live_wps and "items" in live_wps:
        live_by_id = {item["id"]: item for item in live_wps["items"]}
        for wp_id in linked_ids["live"]:
            if wp_id in live_by_id:
                result["live"].append(live_by_id[wp_id])

    if archive_wps and "items" in archive_wps:
        archive_by_id = {item["id"]: item for item in archive_wps["items"]}
        for wp_id in linked_ids["archive"]:
            if wp_id in archive_by_id:
                result["archive"].append(archive_by_id[wp_id])

    return result


def waypoints_available() -> bool:
    """Check if waypoints core module is available and returns valid data."""
    data = load_live_waypoints()
    return data is not None and data.get("contract") == LIVE_CONTRACT


def get_waypoints_diagnostics() -> dict:
    """Get diagnostics about waypoints integration state."""
    live = load_live_waypoints()
    archive = load_archive_waypoints()

    return {
        "live_available": live is not None,
        "live_contract": live.get("contract") if live else None,
        "live_count": live.get("counts", {}).get("total", 0) if live else 0,
        "archive_available": archive is not None,
        "archive_contract": archive.get("contract") if archive else None,
        "archive_count": archive.get("counts", {}).get("total", 0) if archive else 0,
        "core_module_available": WAYPOINTS_AVAILABLE,
        "waypoints_path": _WAYPOINTS_PATH,
    }