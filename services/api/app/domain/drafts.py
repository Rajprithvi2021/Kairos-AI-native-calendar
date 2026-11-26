"""Deterministic message templates (the offline twin of the Claude draft writer).

Claude can rewrite any of these on request (POST /api/ai/draft); the template guarantees a sensible,
factual default with no hallucinated details.
"""

from __future__ import annotations

from app.domain.calendar_data import Ev, Snapshot
from app.domain.timeutils import fmt_local


def _first(snap: Snapshot, pid: str) -> str:
    p = snap.people.get(pid)
    return p.first_name if p else "there"


def decline_note(ev: Ev, because: Ev | None, snap: Snapshot, uid: str) -> dict[str, str]:
    me = _first(snap, uid)
    org = _first(snap, ev.organizer_id)
    reason = f"a conflict with a higher-priority meeting ({because.title})" if because else "a conflict"
    body = (
        f"Hi {org},\n\nI'm sorry to miss \u201c{ev.title}\u201d \u2014 I have {reason} at that time. "
        "Could you share notes or the recording afterwards? If there's anything that needs my input, "
        "drop it in the doc and I'll reply asynchronously the same day.\n\nThanks,\n" + me
    )
    return {"subject": f"Can't make it: {ev.title}", "body": body}


def reschedule_request(ev: Ev, snap: Snapshot, uid: str, proposal: str | None = None) -> dict[str, str]:
    me = _first(snap, uid)
    org = _first(snap, ev.organizer_id)
    alt = f" Would {proposal} work instead?" if proposal else " Could we find another time this week?"
    body = f"Hi {org},\n\nI've hit a conflict with \u201c{ev.title}\u201d.{alt}\n\nThanks,\n{me}"
    return {"subject": f"Reschedule request: {ev.title}", "body": body}


def remote_join_note(ev: Ev, snap: Snapshot, uid: str, travel_min: int) -> dict[str, str]:
    me = _first(snap, uid)
    org = _first(snap, ev.organizer_id)
    body = (
        f"Hi {org},\n\nI'm coming straight from an onsite and can't make it back in time "
        f"(~{travel_min} min of travel), so I'll join \u201c{ev.title}\u201d by video. "
        "Could someone share a dial-in link?\n\nThanks,\n" + me
    )
    return {"subject": f"Joining remotely: {ev.title}", "body": body}


def shorten_series_note(title: str, old_min: int, new_min: int, me: str) -> dict[str, str]:
    body = (
        f"Hi team,\n\nOur \u201c{title}\u201d has been finishing early most weeks, so from next week I'm trimming it "
        f"from {old_min} to {new_min} minutes. Status updates move to the shared doc beforehand, and the meeting is "
        "for decisions and blockers only.\n\nThanks,\n" + me
    )
    return {"subject": f"{title}: now {new_min} minutes", "body": body}


def async_update_note(title: str, organizer_first: str, me: str) -> dict[str, str]:
    body = (
        f"Hi {organizer_first},\n\nI'm optional on \u201c{title}\u201d and usually only need the decisions. "
        "I'll step out of the live meeting and follow the notes instead \u2014 please @-mention me if you need input.\n\n"
        "Thanks,\n" + me
    )
    return {"subject": f"Following {title} asynchronously", "body": body}


def followup_recap(ev: Ev, snap: Snapshot, uid: str) -> dict[str, str]:
    me = _first(snap, uid)
    names = ", ".join(_first(snap, p) for p in ev.participant_ids() if p != uid) or "all"
    tz = snap.people[uid].timezone
    body = (
        f"Hi {names},\n\nThanks for the time today ({fmt_local(ev.start, tz)}). Recap of \u201c{ev.title}\u201d:\n\n"
        "Decisions\n- \n\nAction items\n- [owner] [action] by [date]\n\nOpen questions\n- \n\nBest,\n" + me
    )
    return {"subject": f"Recap: {ev.title}", "body": body}
