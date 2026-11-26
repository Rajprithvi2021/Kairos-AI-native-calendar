"""Optional Google Calendar connector (read path).

Not active in the demo: it needs your own Google Cloud project, the Calendar API enabled and an OAuth
client (Desktop app) JSON. Install the extra and point KAIROS_GOOGLE_CLIENT_SECRETS at the file:
    uv sync --extra google
    $env:KAIROS_GOOGLE_CLIENT_SECRETS = "C:\\path\\to\\client_secret.json"
Scope requested: calendar.readonly (least privilege). Production uses push notifications
(events.watch) plus incremental sync tokens instead of polling - see docs/04.

`to_kairos_event` is pure and unit-tested with a recorded API payload, so the mapping is verified
even without credentials.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import Settings

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
RESPONSE = {"accepted": "accepted", "declined": "declined", "tentative": "tentative", "needsAction": "needsAction"}


def status(settings: Settings) -> dict[str, Any]:
    libs = importlib.util.find_spec("googleapiclient") is not None and importlib.util.find_spec("google_auth_oauthlib") is not None
    secrets = bool(settings.google_client_secrets) and Path(settings.google_client_secrets or "").is_file()
    if not libs:
        msg = "Google client libraries not installed (uv sync --extra google)."
    elif not secrets:
        msg = "Set KAIROS_GOOGLE_CLIENT_SECRETS to your OAuth client JSON (Calendar API enabled)."
    else:
        msg = "Ready to connect."
    return {"configured": libs and secrets, "libraries": libs, "client_secrets": secrets, "scopes": SCOPES, "message": msg}


def _dt(value: dict[str, Any]) -> datetime | None:
    if "dateTime" not in value:
        return None  # all-day
    return datetime.fromisoformat(value["dateTime"].replace("Z", "+00:00")).astimezone(UTC)


def to_kairos_event(item: dict[str, Any], uid: str, by_email: dict[str, str]) -> dict[str, Any] | None:
    """Map one Google Calendar API `Event` resource to a Kairos create-operation payload."""
    if item.get("status") == "cancelled":
        return None
    start, end = _dt(item.get("start", {})), _dt(item.get("end", {}))
    if start is None or end is None or end <= start:
        return None
    organizer = by_email.get(item.get("organizer", {}).get("email", "").lower(), uid)
    atts = []
    for a in item.get("attendees", []):
        pid = by_email.get(a.get("email", "").lower())
        if pid:
            atts.append({"person_id": pid, "response": RESPONSE.get(a.get("responseStatus", "needsAction"), "needsAction"),
                         "optional": bool(a.get("optional", False))})
    if not any(a["person_id"] == uid for a in atts):
        atts.insert(0, {"person_id": uid, "response": "accepted", "optional": False})
    kind = "focus" if item.get("eventType") == "focusTime" else "meeting"
    location = item.get("location")
    return {
        "title": item.get("summary", "(no title)"),
        "description": (item.get("description") or "")[:2000],
        "start": start,
        "end": end,
        "organizer_id": organizer,
        "attendees": atts,
        "kind": kind,
        "location": location,
        "is_virtual": bool(item.get("hangoutLink") or item.get("conferenceData")) or not location,
        "is_movable": organizer == uid,
        "source": "google",
        "external_ref": f"google:{item.get('id')}",
    }
