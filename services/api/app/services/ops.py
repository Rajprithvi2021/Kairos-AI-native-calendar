"""Write side. Every change goes through `apply_operations`, which records an audit entry with
before/after snapshots - so every AI (or human) change is explainable and reversible (undo)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlmodel import Session

from app.clock import parse_utc
from app.models import AuditEntry, BriefCache, Event, Preferences, Proposal, TelemetryEvent

UPDATABLE = {
    "title",
    "description",
    "start",
    "end",
    "location",
    "is_virtual",
    "status",
    "attendees",
    "kind",
    "category",
    "is_movable",
}
_DT_FIELDS = {"start", "end", "created_at"}


class OpError(ValueError):
    pass


class VersionConflict(OpError):
    pass


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _coerce(field: str, value: Any) -> Any:
    if field in _DT_FIELDS and isinstance(value, str):
        return parse_utc(value)
    return value


def event_snapshot(row: Event) -> dict[str, Any]:
    return row.model_dump(mode="json")


def _restore(row: Event, snap: dict[str, Any]) -> None:
    for k, v in snap.items():
        if k == "id":
            continue
        setattr(row, k, _coerce(k, v))


def apply_operations(
    session: Session,
    ops: list[dict[str, Any]],
    *,
    action: str,
    summary: str,
    now: datetime,
    actor: str = "user",
    proposal_id: str | None = None,
) -> AuditEntry:
    changes: list[dict[str, Any]] = []
    touched: set[str] = set()
    for op in ops:
        kind = op.get("op")
        if kind == "create":
            data = {k: _coerce(k, v) for k, v in dict(op["event"]).items()}
            data.setdefault("id", new_id("ev"))
            data.setdefault("created_at", now)
            if data["end"] <= data["start"]:
                raise OpError("event must end after it starts")
            row = Event(**data)
            session.add(row)
            changes.append({"op": "create", "event_id": row.id, "before": None, "after": event_snapshot(row)})
        elif kind in ("update", "delete", "respond"):
            row = session.get(Event, op.get("event_id"))
            if row is None:
                raise OpError(f"event {op.get('event_id')} not found")
            expected = op.get("expected_version")
            if expected is not None and expected != row.version:
                raise VersionConflict(f"event {row.id} changed since you loaded it (v{row.version})")
            before = event_snapshot(row)
            if kind == "update":
                for k, v in op.get("changes", {}).items():
                    if k not in UPDATABLE:
                        raise OpError(f"field {k} is not updatable")
                    setattr(row, k, _coerce(k, v))
                if row.end <= row.start:
                    raise OpError("event must end after it starts")
            elif kind == "delete":
                row.status = "cancelled"
            else:  # respond
                atts = [dict(a) for a in row.attendees]
                found = False
                for a in atts:
                    if a["person_id"] == op["person_id"]:
                        a["response"] = op["response"]
                        found = True
                if not found:
                    atts.append({"person_id": op["person_id"], "response": op["response"], "optional": False})
                row.attendees = atts
            row.version += 1
            touched.add(row.id)
            changes.append({"op": kind, "event_id": row.id, "before": before, "after": event_snapshot(row)})
        elif kind == "dismiss_conflict":
            prefs = session.get(Preferences, op["person_id"])
            if prefs is None:
                raise OpError("preferences not found")
            before_list = list(prefs.dismissed_conflicts)
            prefs.dismissed_conflicts = before_list + [op["conflict_id"]]
            changes.append({"op": kind, "person_id": op["person_id"], "before": before_list, "after": prefs.dismissed_conflicts})
        else:
            raise OpError(f"unknown operation {kind!r}")
    for eid in touched:  # cached AI briefs may be stale now
        cached = session.get(BriefCache, eid)
        if cached:
            session.delete(cached)
    entry = AuditEntry(
        id=new_id("au"),
        proposal_id=proposal_id,
        action=action,
        actor=actor,
        summary=summary,
        changes=changes,
        created_at=now,
    )
    session.add(entry)
    session.commit()
    return entry


def _content(snap: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in snap.items() if k != "version"}


def undo(session: Session, audit_id: str) -> AuditEntry:
    entry = session.get(AuditEntry, audit_id)
    if entry is None:
        raise OpError("audit entry not found")
    if entry.undone:
        raise OpError("already undone")
    # Refuse rather than clobber: each event must still look exactly as this action left it. Compare content,
    # not version numbers, so undoing a later change first (which bumps the version) re-enables this undo.
    final_after: dict[str, dict[str, Any]] = {}
    for ch in entry.changes:
        if ch["op"] in ("create", "update", "delete", "respond"):
            final_after[ch["event_id"]] = ch["after"]
    for event_id, after in final_after.items():
        row = session.get(Event, event_id)
        if row is not None and _content(event_snapshot(row)) != _content(after):
            raise VersionConflict(f"“{row.title}” has changed since this action; undo the later change first")
    touched: set[str] = set()
    for ch in reversed(entry.changes):
        op = ch["op"]
        if op == "create":
            row = session.get(Event, ch["event_id"])
            if row is not None:
                session.delete(row)
                touched.add(row.id)
        elif op in ("update", "delete", "respond"):
            row = session.get(Event, ch["event_id"])
            if row is not None:
                current = row.version
                _restore(row, ch["before"])
                row.version = current + 1  # a new version: clients still holding the pre-undo one get a 409
                touched.add(row.id)
        elif op == "dismiss_conflict":
            prefs = session.get(Preferences, ch["person_id"])
            if prefs is not None:  # remove only what this action dismissed; keep later dismissals
                added = set(ch["after"]) - set(ch["before"])
                prefs.dismissed_conflicts = [c for c in prefs.dismissed_conflicts if c not in added]
    for eid in touched:  # cached AI briefs describe the pre-undo event
        cached = session.get(BriefCache, eid)
        if cached:
            session.delete(cached)
    entry.undone = True
    if entry.proposal_id:
        prop = session.get(Proposal, entry.proposal_id)
        if prop is not None:
            prop.status = "undone"
    session.commit()
    return entry


# --- proposals --------------------------------------------------------------------------------
def create_proposal(
    session: Session,
    *,
    kind: str,
    title: str,
    summary: str,
    operations: list[dict[str, Any]],
    explanation: dict[str, Any],
    now: datetime,
    source: str = "engine",
) -> Proposal:
    prop = Proposal(
        id=new_id("pr"),
        kind=kind,
        title=title,
        summary=summary,
        operations=operations,
        explanation=explanation,
        source=source,
        created_at=now,
    )
    session.add(prop)
    session.commit()
    return prop


def apply_proposal(session: Session, proposal_id: str, now: datetime, actor: str = "user") -> AuditEntry:
    prop = session.get(Proposal, proposal_id)
    if prop is None:
        raise OpError("proposal not found")
    if prop.status != "pending":
        raise OpError(f"proposal is {prop.status}")
    entry = apply_operations(
        session, prop.operations, action=prop.kind, summary=prop.title, now=now, actor=actor, proposal_id=prop.id
    )
    prop.status = "applied"
    prop.audit_id = entry.id
    session.commit()
    return entry


def proposal_dict(p: Proposal) -> dict[str, Any]:
    return {
        "id": p.id,
        "kind": p.kind,
        "title": p.title,
        "summary": p.summary,
        "operations": p.operations,
        "explanation": p.explanation,
        "status": p.status,
        "source": p.source,
        "created_at": p.created_at.isoformat(),
        "audit_id": p.audit_id,
    }


def audit_dict(a: AuditEntry) -> dict[str, Any]:
    return {
        "id": a.id,
        "proposal_id": a.proposal_id,
        "action": a.action,
        "actor": a.actor,
        "summary": a.summary,
        "change_count": len(a.changes),
        "created_at": a.created_at.isoformat(),
        "undone": a.undone,
    }


# --- telemetry (local only; powers Study mode metrics) ----------------------------------------
def track(session: Session, name: str, now: datetime, props: dict[str, Any] | None = None, participant_id: str | None = None) -> None:
    session.add(TelemetryEvent(name=name, props=props or {}, participant_id=participant_id, created_at=now))
    session.commit()
