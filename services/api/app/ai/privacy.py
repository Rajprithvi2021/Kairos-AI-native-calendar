"""Data minimisation before anything leaves the process for an LLM.

- Only what the task needs (no emails, no free/busy of others, no unrelated events).
- External people can be pseudonymised ("External: COO at Brightwave Logistics").
- Event titles can be replaced by their category when the user opts out of sending titles.
- Invite text written by third parties is fenced as untrusted data (prompt-injection hygiene).
"""

from __future__ import annotations

import re
from typing import Any

from app.domain.classify import category_label

_TAG = re.compile(r"</?\s*untrusted[^>]*>", re.I)


def person_label(p: Any, redact_external: bool) -> str:
    if p.is_external and redact_external:
        return f"External: {p.title} at {p.company}"
    return f"{p.name} ({p.title}{'' if not p.is_external else ', ' + p.company})"


def event_title(ev: Any, send_titles: bool) -> str:
    return ev.title if send_titles else f"[{category_label(ev.category)} meeting]"


def fence_untrusted(text: str, limit: int = 1500) -> str:
    """Wrap third-party text so the model treats it as data, never as instructions."""
    cleaned = _TAG.sub("", text or "")[:limit]
    return f"<untrusted_invite_text>\n{cleaned}\n</untrusted_invite_text>"
