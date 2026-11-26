"""Actions & research: proposals, direct operations, audit/undo, feedback, telemetry, study mode."""

from __future__ import annotations

import csv
import io
import statistics
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.api.deps import http_errors, now_dep, session_dep
from app.domain.timeutils import iso
from app.models import AuditEntry, Feedback, Proposal, StudyResult, TelemetryEvent
from app.services import ops

router = APIRouter(prefix="/api")


@router.get("/proposals")
def list_proposals(status: str = "pending", session: Session = Depends(session_dep)) -> list[dict[str, Any]]:
    rows = session.exec(select(Proposal).where(Proposal.status == status).order_by(Proposal.created_at.desc())).all()  # type: ignore[attr-defined]
    return [ops.proposal_dict(p) for p in rows[:50]]


@router.post("/proposals/{proposal_id}/apply")
@http_errors
def apply_proposal(proposal_id: str, session: Session = Depends(session_dep), now: datetime = Depends(now_dep)) -> dict[str, Any]:
    entry = ops.apply_proposal(session, proposal_id, now)
    prop = session.get(Proposal, proposal_id)
    ops.track(session, "proposal_applied", now, {"kind": prop.kind if prop else None})
    return {"audit_id": entry.id, "summary": entry.summary}


@router.post("/proposals/{proposal_id}/discard")
def discard_proposal(proposal_id: str, session: Session = Depends(session_dep), now: datetime = Depends(now_dep)) -> dict[str, Any]:
    prop = session.get(Proposal, proposal_id)
    if prop is None:
        raise HTTPException(404, "proposal not found")
    if prop.status == "pending":
        prop.status = "discarded"
        session.commit()
        ops.track(session, "proposal_discarded", now, {"kind": prop.kind})
    return {"status": prop.status}


class OpsBody(BaseModel):
    operations: list[dict[str, Any]] = Field(min_length=1, max_length=50)
    summary: str = "Applied suggestion"
    action: str = "apply_suggestion"


@router.post("/operations")
@http_errors
def apply_ops(body: OpsBody, session: Session = Depends(session_dep), now: datetime = Depends(now_dep)) -> dict[str, Any]:
    try:
        entry = ops.apply_operations(session, body.operations, action=body.action, summary=body.summary, now=now)
    except KeyError as e:  # a malformed operation is a bad request, not a missing resource
        raise ops.OpError(f"malformed operation: missing {e}") from e
    ops.track(session, "proposal_applied", now, {"kind": body.action})
    return {"audit_id": entry.id, "summary": entry.summary}


@router.get("/audit")
def audit(limit: int = 20, session: Session = Depends(session_dep)) -> list[dict[str, Any]]:
    rows = session.exec(select(AuditEntry).order_by(AuditEntry.created_at.desc()).limit(min(limit, 100))).all()  # type: ignore[attr-defined]
    return [ops.audit_dict(a) for a in rows]


@router.post("/audit/{audit_id}/undo")
@http_errors
def undo(audit_id: str, session: Session = Depends(session_dep), now: datetime = Depends(now_dep)) -> dict[str, Any]:
    entry = ops.undo(session, audit_id)
    ops.track(session, "undo", now, {"action": entry.action})
    return {"undone": True, "summary": entry.summary}


# --- research instrumentation (local only) ------------------------------------------------------------
class FeedbackBody(BaseModel):
    target_type: str
    target_id: str
    rating: int = Field(ge=-1, le=1)
    reasons: list[str] = []
    comment: str = ""
    participant_id: str | None = None


@router.post("/feedback")
def feedback(body: FeedbackBody, session: Session = Depends(session_dep), now: datetime = Depends(now_dep)) -> dict[str, Any]:
    fb = Feedback(id=f"fb_{uuid.uuid4().hex[:10]}", created_at=now, **body.model_dump())
    session.add(fb)
    session.commit()
    return {"id": fb.id}


class TelemetryBody(BaseModel):
    name: str
    props: dict[str, Any] = {}
    participant_id: str | None = None


@router.post("/telemetry")
def telemetry(body: TelemetryBody, session: Session = Depends(session_dep), now: datetime = Depends(now_dep)) -> dict[str, Any]:
    ops.track(session, body.name[:60], now, body.props, body.participant_id)
    return {"ok": True}


class StudyBody(BaseModel):
    participant_id: str
    task_id: str
    duration_s: float | None = None
    success: str = "yes"
    seq: int | None = Field(default=None, ge=1, le=7)
    notes: str = ""


@router.post("/research/results")
def study_result(body: StudyBody, session: Session = Depends(session_dep), now: datetime = Depends(now_dep)) -> dict[str, Any]:
    if body.success not in ("yes", "partial", "no"):
        raise HTTPException(400, "success must be yes, partial or no")
    row = StudyResult(id=f"sr_{uuid.uuid4().hex[:10]}", created_at=now, **body.model_dump())
    session.add(row)
    session.commit()
    return {"id": row.id}


@router.get("/research/metrics")
def metrics(session: Session = Depends(session_dep)) -> dict[str, Any]:
    events = session.exec(select(TelemetryEvent)).all()
    counts: dict[str, int] = {}
    ranks: list[int] = []
    for e in events:
        counts[e.name] = counts.get(e.name, 0) + 1
        if e.name == "slot_booked" and isinstance(e.props.get("rank"), int):
            ranks.append(e.props["rank"])
    applied = counts.get("slot_booked", 0) + counts.get("proposal_applied", 0)
    shown = counts.get("suggestion_shown", 0)
    fbs = session.exec(select(Feedback)).all()
    results = session.exec(select(StudyResult)).all()
    by_task: dict[str, list[StudyResult]] = {}
    for r in results:
        by_task.setdefault(r.task_id, []).append(r)
    tasks = []
    for tid, rows in sorted(by_task.items()):
        durations = [r.duration_s for r in rows if r.duration_s]
        seqs = [r.seq for r in rows if r.seq]
        tasks.append({"task_id": tid, "n": len(rows),
                      "success_rate": round(sum(1 for r in rows if r.success == "yes") / len(rows), 2),
                      "median_time_s": round(statistics.median(durations), 1) if durations else None,
                      "mean_seq": round(statistics.mean(seqs), 2) if seqs else None})
    return {
        "suggestions_shown": shown,
        "actions_applied": applied,
        "acceptance_rate": round(applied / shown, 2) if shown else None,
        "undo_rate": round(counts.get("undo", 0) / applied, 2) if applied else None,
        "avg_rank_picked": round(statistics.mean(ranks), 2) if ranks else None,
        "feedback": {"up": sum(1 for f in fbs if f.rating > 0), "down": sum(1 for f in fbs if f.rating < 0)},
        "commands": counts.get("command_submitted", 0),
        "tasks": tasks,
        "counts": counts,
    }


@router.get("/research/export.csv")
def export_csv(session: Session = Depends(session_dep)) -> Response:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["section", "id", "participant_id", "name_or_task", "value", "detail", "created_at"])
    for r in session.exec(select(StudyResult)).all():
        w.writerow(["study", r.id, r.participant_id, r.task_id, r.success, f"duration_s={r.duration_s};seq={r.seq};notes={r.notes}", iso(r.created_at)])
    for f in session.exec(select(Feedback)).all():
        w.writerow(["feedback", f.id, f.participant_id or "", f"{f.target_type}:{f.target_id}", f.rating, ";".join(f.reasons) + (" | " + f.comment if f.comment else ""), iso(f.created_at)])
    for t in session.exec(select(TelemetryEvent)).all():
        w.writerow(["telemetry", t.id, t.participant_id or "", t.name, "", str(t.props), iso(t.created_at)])
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=kairos-research.csv"})
