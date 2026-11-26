"""Synthetic demo world for "Lumora" (fictional), anchored to `now` so the demo never goes stale.

Design goals
- Realistic load: recurring 1:1s/syncs plus ad-hoc meetings with realistic booking lead times.
  Future events whose booking time is still in the future are dropped, so upcoming weeks look
  lighter than they will end up - exactly the signal the forecaster must learn to correct.
- Four time zones (SF, New York, London, Bangalore) and three holiday calendars (US, GB, IN).
- Planted scenarios on the next business days that exercise every engine: an overlap, impossible
  travel, a focus-block intrusion, an overloaded day, an outside-hours meeting, recurring meetings
  that are unfair to Bangalore, and series that could be shorter or async.
All people, companies and emails are fictional (example.* domains).
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlmodel import Session, delete

from app.domain.calendar_data import holidays_for
from app.domain.classify import categorize
from app.domain.timeutils import local_to_utc, parse_hhmm, to_local, week_start
from app.models import (
    AiCallLog,
    AuditEntry,
    BriefCache,
    Event,
    Feedback,
    Person,
    Preferences,
    Proposal,
    ReminderSetting,
    Series,
    StudyResult,
    TelemetryEvent,
)

USER_ID = "maya"

PEOPLE: list[dict[str, Any]] = [
    dict(id="maya", name="Maya Chen", title="VP Customer Success", team="Customer Success", timezone="America/Los_Angeles",
         country="US", city="San Francisco", work_start="08:00", work_end="17:30", seniority=4, hourly_rate=160,
         color="#6366f1", manager_id="jordan"),
    dict(id="jordan", name="Jordan Lee", title="CEO", team="Executive", timezone="America/Los_Angeles", country="US",
         city="San Francisco", work_start="08:30", work_end="18:00", seniority=5, hourly_rate=250, color="#0ea5e9"),
    dict(id="omar", name="Omar Haddad", title="VP Engineering", team="Engineering", timezone="America/Los_Angeles",
         country="US", city="San Francisco", work_start="08:30", work_end="17:30", seniority=4, hourly_rate=170,
         color="#14b8a6", manager_id="jordan"),
    dict(id="dev", name="Dev Patel", title="Engineering Manager, CS Tooling", team="Engineering",
         timezone="America/Los_Angeles", country="US", city="San Francisco", work_start="08:00", work_end="17:00",
         seniority=3, hourly_rate=130, color="#22c55e", manager_id="omar"),
    dict(id="priya", name="Priya Nair", title="Senior Software Engineer", team="Engineering", timezone="Asia/Kolkata",
         country="IN", city="Bangalore", work_start="10:00", work_end="18:30", seniority=2, hourly_rate=70,
         color="#a855f7", manager_id="dev"),
    dict(id="alex", name="Alex Kim", title="Director, Account Management", team="Customer Success",
         timezone="America/New_York", country="US", city="New York", work_start="08:30", work_end="17:00",
         seniority=3, hourly_rate=120, color="#f59e0b", manager_id="maya"),
    dict(id="emma", name="Emma Clarke", title="Head of EMEA Success", team="Customer Success",
         timezone="Europe/London", country="GB", city="London", work_start="08:30", work_end="17:00", seniority=3,
         hourly_rate=115, color="#ef4444", manager_id="maya"),
    dict(id="arjun", name="Arjun Rao", title="Support Lead", team="Customer Success", timezone="Asia/Kolkata",
         country="IN", city="Bangalore", work_start="09:30", work_end="18:00", seniority=2, hourly_rate=60,
         color="#84cc16", manager_id="maya"),
    dict(id="sam", name="Sam Ortiz", title="Executive Assistant", team="Executive", timezone="America/Los_Angeles",
         country="US", city="San Francisco", work_start="08:00", work_end="16:30", seniority=2, hourly_rate=55,
         color="#f472b6", manager_id="jordan"),
    dict(id="nina", name="Nina Alvarez", title="Product Manager", team="Product", timezone="America/New_York",
         country="US", city="New York", work_start="09:00", work_end="17:30", seniority=2, hourly_rate=110,
         color="#06b6d4"),
    dict(id="leo", name="Leo Martins", title="Account Executive", team="Sales", timezone="America/New_York",
         country="US", city="New York", work_start="08:30", work_end="17:00", seniority=2, hourly_rate=100,
         color="#eab308"),
    dict(id="lena", name="Lena Fischer", title="Senior Recruiter", team="People", timezone="America/Los_Angeles",
         country="US", city="San Francisco", work_start="08:30", work_end="17:00", seniority=2, hourly_rate=80,
         color="#fb7185"),
    # External contacts (fictional companies)
    dict(id="olivia", name="Olivia Park", title="COO", company="Brightwave Logistics", timezone="America/Los_Angeles",
         country="US", city="Oakland", is_external=True, seniority=4, hourly_rate=0, color="#78716c"),
    dict(id="daniel", name="Daniel Osei", title="VP Operations", company="Cobalt Health", timezone="America/Los_Angeles",
         country="US", city="Palo Alto", is_external=True, seniority=4, hourly_rate=0, color="#78716c"),
    dict(id="hannah", name="Hannah Weiss", title="Director of IT", company="Fernway Retail", timezone="America/Chicago",
         country="US", city="Chicago", is_external=True, seniority=3, hourly_rate=0, color="#78716c"),
    dict(id="marco", name="Marco Silva", title="Account Executive", company="InsightHub", timezone="America/Los_Angeles",
         country="US", city="San Francisco", is_external=True, seniority=2, hourly_rate=0, color="#78716c"),
]

_DOMAINS = {"Lumora": "lumora.example", "Brightwave Logistics": "brightwave.example", "Cobalt Health": "cobalthealth.example",
            "Fernway Retail": "fernway.example", "InsightHub": "insighthub.example"}


@dataclass
class SeriesSpec:
    id: str
    title: str
    organizer: str
    days: list[int]
    time: str
    duration: int
    attendees: list[str]
    category: str
    kind: str = "meeting"
    optional: list[str] = field(default_factory=list)
    avg_actual_min: float | None = None
    attendance: float | None = None
    movable: bool = True
    notes: str = ""


SERIES: list[SeriesSpec] = [
    SeriesSpec("s_standup", "CS leadership standup", "maya", [0, 1, 2, 3], "09:00", 15, ["alex", "sam"], "team",
               avg_actual_min=14, attendance=0.96),
    SeriesSpec("s_1on1_emma", "1:1 Maya / Emma", "maya", [0], "08:00", 30, ["emma"], "one_on_one", avg_actual_min=29, attendance=1.0),
    SeriesSpec("s_exec_staff", "Exec staff meeting", "jordan", [0], "13:00", 60, ["maya", "omar"], "leadership",
               avg_actual_min=58, attendance=0.98, movable=False),
    SeriesSpec("s_cs_team", "Weekly CS team meeting", "maya", [1], "08:00", 60, ["alex", "emma", "arjun", "sam", "nina"], "team",
               avg_actual_min=38, attendance=1.0, notes="Mostly status updates read out loud."),
    SeriesSpec("s_1on1_alex", "1:1 Maya / Alex", "maya", [2], "08:30", 30, ["alex"], "one_on_one", avg_actual_min=27, attendance=1.0),
    SeriesSpec("s_tooling", "CS tooling sync", "dev", [3], "08:00", 45, ["maya", "priya", "arjun"], "team",
               avg_actual_min=41, attendance=0.9, movable=False),
    SeriesSpec("s_1on1_jordan", "1:1 Jordan / Maya", "jordan", [3], "16:00", 30, ["maya"], "one_on_one",
               avg_actual_min=30, attendance=1.0, movable=False),
    SeriesSpec("s_pipeline", "Pipeline & renewals review", "alex", [4], "13:00", 60, ["leo", "nina"], "planning",
               optional=["maya"], avg_actual_min=55, attendance=0.4, movable=False),
    SeriesSpec("s_focus", "Focus: deep work", "maya", [1, 3], "13:00", 120, [], "focus", kind="focus"),
]

CUSTOMERS = [("Brightwave Logistics", "olivia"), ("Cobalt Health", "daniel"), ("Fernway Retail", "hannah")]
CUSTOMER_TOPICS = ["renewal check-in", "onboarding sync", "adoption review", "roadmap preview", "support follow-up"]
ADHOC = ["Sync: renewal pricing", "Sync: churn-risk accounts", "Sync: support SLA", "Sync: onboarding playbook",
         "Sync: QBR deck review", "Sync: CS headcount"]
PLANNING = ["Renewal forecast review", "FY27 planning workshop", "Churn analysis readout"]
COLLEAGUE_TITLES = ["Design review", "Customer call", "Hiring sync", "Project check-in", "Planning", "1:1"]


@dataclass
class World:
    people: list[Person]
    prefs: list[Preferences]
    series: list[Series]
    events: list[Event]
    business_days: list[date]


class _Builder:
    def __init__(self, now: datetime, seed: int) -> None:
        self.now = now
        self.rng = random.Random(seed)
        self.people: dict[str, Person] = {}
        for spec in PEOPLE:
            p = Person(**spec, email="")
            p.email = f"{p.first_name.lower()}@{_DOMAINS.get(p.company, 'example.com')}"
            self.people[p.id] = p
        self.user = self.people[USER_ID]
        self.today = to_local(now, self.user.timezone).date()
        self.this_monday = week_start(self.today)
        self.range_start = self.this_monday - timedelta(weeks=12)
        self.range_end = self.this_monday + timedelta(weeks=5)  # exclusive
        self.long_ago = local_to_utc(self.range_start, parse_hhmm("09:00"), self.user.timezone) - timedelta(days=30)
        span = (self.range_start - timedelta(days=7), self.range_end + timedelta(days=7))
        self.hol = {pid: set(holidays_for(p.country, *span)) for pid, p in self.people.items()}
        self.events: list[Event] = []
        self.busy: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
        self.counter = 0
        self.planted_days = self._next_business_days(4)

    # --- helpers ------------------------------------------------------------------------------
    def at(self, d: date, hhmm: str, pid: str = USER_ID) -> datetime:
        return local_to_utc(d, parse_hhmm(hhmm), self.people[pid].timezone)

    def is_free(self, pid: str, s: datetime, e: datetime) -> bool:
        return all(not (s < b and a < e) for a, b in self.busy[pid])

    def within_hours(self, pid: str, s: datetime, e: datetime, slack_min: int = 0) -> bool:
        p = self.people[pid]
        ls, le = to_local(s, p.timezone), to_local(e, p.timezone)
        if ls.date() in self.hol[pid] or ls.weekday() not in p.work_days:
            return False
        ws = ls.replace(hour=int(p.work_start[:2]), minute=int(p.work_start[3:]))
        we = ls.replace(hour=int(p.work_end[:2]), minute=int(p.work_end[3:]))
        return ls >= ws - timedelta(minutes=slack_min) and le <= we + timedelta(minutes=slack_min)

    def _next_business_days(self, n: int) -> list[date]:
        out, d = [], self.today
        while len(out) < n:
            d += timedelta(days=1)
            if d.weekday() < 5 and d not in self.hol[USER_ID]:
                out.append(d)
        return out

    def _lead_time(self, start: datetime, urgent: bool = False) -> datetime:
        r = self.rng.random()
        if urgent:
            hours = self.rng.uniform(2, 20)
        elif r < 0.35:
            hours = self.rng.uniform(3, 48)
        elif r < 0.70:
            hours = self.rng.uniform(72, 168)
        else:
            hours = self.rng.uniform(192, 504)
        return start - timedelta(hours=hours)

    def add(
        self,
        *,
        title: str,
        start: datetime,
        end: datetime,
        organizer: str,
        attendees: list[str] | tuple[str, ...] = (),
        optional: list[str] | tuple[str, ...] = (),
        kind: str = "meeting",
        location: str | None = None,
        is_virtual: bool = True,
        is_movable: bool = True,
        series_id: str | None = None,
        created_at: datetime | None = None,
        description: str = "",
        eid: str | None = None,
        urgent: bool = False,
    ) -> Event | None:
        created = created_at or self._lead_time(start, urgent)
        if created > self.now:
            return None  # not booked yet as of "now"
        atts = []
        for pid in dict.fromkeys([organizer, *attendees, *optional]):
            local_day = to_local(start, self.people[pid].timezone).date()
            resp = "declined" if (local_day in self.hol[pid] and pid != organizer) else "accepted"
            atts.append({"person_id": pid, "response": resp, "optional": pid in optional})
        cat = categorize(title, kind, [self.people[a["person_id"]] for a in atts])
        self.counter += 1
        ev = Event(
            id=eid or f"ev_{self.counter:05d}", title=title, description=description, start=start, end=end,
            organizer_id=organizer, attendees=atts, kind=kind, category=cat, location=location,
            is_virtual=is_virtual, is_movable=is_movable, series_id=series_id, created_at=created, source="seed",
        )
        self.events.append(ev)
        for a in atts:
            if a["response"] != "declined":
                self.busy[a["person_id"]].append((start, end))
        return ev

    def remove_user_overlaps(self, s: datetime, e: datetime) -> None:
        keep = []
        for ev in self.events:
            mine = any(a["person_id"] == USER_ID for a in ev.attendees)
            if mine and ev.start < e and s < ev.end and not ev.id.startswith("plant_"):
                continue
            keep.append(ev)
        self.events = keep
        self.busy[USER_ID] = [
            (ev.start, ev.end) for ev in self.events
            if any(a["person_id"] == USER_ID and a["response"] != "declined" for a in ev.attendees)
        ]

    # --- builders -----------------------------------------------------------------------------
    def build_series(self) -> list[Series]:
        out = []
        for spec in SERIES:
            out.append(
                Series(
                    id=spec.id, title=spec.title, organizer_id=spec.organizer,
                    cadence=", ".join(["Mon", "Tue", "Wed", "Thu", "Fri"][d] for d in spec.days) + f" {spec.time}",
                    duration_min=spec.duration, category=spec.category, avg_actual_min=spec.avg_actual_min,
                    user_attendance_rate=spec.attendance, user_optional=USER_ID in spec.optional, notes=spec.notes,
                )
            )
            d = self.range_start
            while d < self.range_end:
                if d.weekday() in spec.days and d not in self.hol[spec.organizer]:
                    s = self.at(d, spec.time, spec.organizer)
                    self.add(
                        title=spec.title, start=s, end=s + timedelta(minutes=spec.duration), organizer=spec.organizer,
                        attendees=spec.attendees, optional=spec.optional, kind=spec.kind, series_id=spec.id,
                        created_at=self.long_ago, is_movable=spec.movable,
                    )
                d += timedelta(days=1)
        return out

    def _place_for_user(self, title: str, duration: int, attendees: list[str], monday: date, urgent: bool = False) -> None:
        days = [monday + timedelta(days=i) for i in range(5)]
        days = [d for d in days if d not in self.hol[USER_ID] and d not in self.planted_days]
        if not days:
            return
        internal = [a for a in attendees if not self.people[a].is_external]
        for _ in range(40):
            d = self.rng.choice(days)
            slot = self.rng.randrange(9 * 4, int(17 * 4 - duration / 15))  # quarter-hours from 09:00
            s = self.at(d, f"{slot // 4:02d}:{(slot % 4) * 15:02d}")
            e = s + timedelta(minutes=duration)
            lt = to_local(s, self.user.timezone)
            if 12 <= lt.hour < 13 and self.rng.random() < 0.8:
                continue  # people mostly protect lunch
            if not self.is_free(USER_ID, s, e):
                continue
            if not all(self.within_hours(a, s, e, slack_min=30) and self.is_free(a, s, e) for a in internal):
                continue
            self.add(title=title, start=s, end=e, organizer=USER_ID if self.rng.random() < 0.6 else (internal or [USER_ID])[0],
                     attendees=[USER_ID, *attendees], urgent=urgent)
            return

    def build_user_oneoffs(self) -> None:
        rng = self.rng
        monday = self.range_start
        while monday < self.range_end:
            for _ in range(rng.randint(2, 4)):
                company, contact = rng.choice(CUSTOMERS)
                self._place_for_user(f"{company} — {rng.choice(CUSTOMER_TOPICS)}", rng.choice([30, 45, 60]),
                                     [contact, rng.choice(["alex", "leo"])], monday)
            for _ in range(rng.randint(1, 2)):
                self._place_for_user(rng.choice(["Interview: Senior CSM candidate", "Interview: Support Engineer candidate"]),
                                     45, ["lena"], monday)
            for _ in range(rng.randint(2, 4)):
                self._place_for_user(rng.choice(ADHOC), 30, rng.sample(["alex", "nina", "dev", "sam", "leo"], rng.randint(1, 2)), monday)
            if rng.random() < 0.6:
                self._place_for_user(rng.choice(PLANNING), 60, ["alex", "nina"], monday)
            if rng.random() < 0.45:
                company, contact = rng.choice(CUSTOMERS)
                self._place_for_user(f"Escalation: {company} data delay", 30, [contact, "alex"], monday, urgent=True)
            monday += timedelta(weeks=1)

    def build_colleagues(self) -> None:
        start = self.this_monday - timedelta(weeks=1)
        for pid, p in self.people.items():
            if p.is_external or pid == USER_ID:
                continue
            d = start
            while d < self.range_end:
                if d.weekday() < 5 and d not in self.hol[pid]:
                    s = self.at(d, "09:30", pid)
                    if self.is_free(pid, s, s + timedelta(minutes=15)):
                        self.add(title="Team standup", start=s, end=s + timedelta(minutes=15), organizer=pid, created_at=self.long_ago)
                    if p.team == "Engineering":
                        s = self.at(d, "14:00", pid)
                        if self.is_free(pid, s, s + timedelta(hours=2)):
                            self.add(title="Focus time", start=s, end=s + timedelta(hours=2), organizer=pid, kind="focus",
                                     created_at=self.long_ago)
                    for _ in range(self.rng.randint(1, 3)):
                        dur = self.rng.choice([30, 45, 60])
                        for _try in range(15):
                            ws = int(p.work_start[:2]) * 4 + int(p.work_start[3:]) // 15
                            we = int(p.work_end[:2]) * 4 + int(p.work_end[3:]) // 15 - dur // 15
                            q = self.rng.randrange(ws, max(ws + 1, we))
                            s = self.at(d, f"{q // 4:02d}:{(q % 4) * 15:02d}", pid)
                            e = s + timedelta(minutes=dur)
                            if self.is_free(pid, s, e):
                                self.add(title=self.rng.choice(COLLEAGUE_TITLES), start=s, end=e, organizer=pid, created_at=self.long_ago)
                                break
                d += timedelta(days=1)

    def plant(self) -> None:
        d0, d1, d2, d3 = self.planted_days
        recent = self.now - timedelta(days=2)

        def group(items: list[dict[str, Any]]) -> None:
            for it in items:
                self.remove_user_overlaps(it["start"], it["end"])
            for it in items:
                self.add(created_at=it.pop("created_at", recent), **it)

        # 1) Overlap: an external QBR lands on top of an internal review the user organises.
        group([
            dict(eid="plant_qbr", title="Brightwave Logistics — QBR", start=self.at(d0, "14:00"), end=self.at(d0, "15:00"),
                 organizer="olivia", attendees=[USER_ID, "alex"], is_movable=False,
                 description="Agenda: adoption metrics, renewal timeline (contract ends Feb 28), expansion to two new warehouses."),
            dict(eid="plant_health", title="Customer health review", start=self.at(d0, "14:00"), end=self.at(d0, "15:00"),
                 organizer=USER_ID, attendees=["alex", "sam"], created_at=self.now - timedelta(days=6)),
        ])
        # 2) Impossible travel: Palo Alto onsite, then an in-person lunch at SF HQ 30 minutes later.
        group([
            dict(eid="plant_onsite", title="Cobalt Health — onsite workshop", start=self.at(d1, "10:00"), end=self.at(d1, "11:30"),
                 organizer="daniel", attendees=[USER_ID], location="Cobalt Health, Palo Alto", is_virtual=False, is_movable=False,
                 description="Workflow mapping with the operations team. Bring the integration timeline."),
            dict(eid="plant_lunch", title="Leadership lunch & learn", start=self.at(d1, "12:00"), end=self.at(d1, "13:00"),
                 organizer="jordan", attendees=[USER_ID, "omar", "dev", "sam"], location="Lumora HQ, San Francisco",
                 is_virtual=False, is_movable=False),
        ])
        # 3) Focus intrusion: a vendor demo inside a protected strategy block.
        group([
            dict(eid="plant_focus", title="Focus: FY27 CS strategy", start=self.at(d2, "10:00"), end=self.at(d2, "12:00"),
                 organizer=USER_ID, kind="focus", created_at=self.now - timedelta(days=9)),
            dict(eid="plant_vendor", title="Vendor demo: InsightHub analytics", start=self.at(d2, "10:30"), end=self.at(d2, "11:15"),
                 organizer="marco", attendees=[USER_ID, "nina"], is_movable=False),
        ])
        # 4) Outside working hours + an overloaded day.
        overload = [
            ("plant_ol_1", "Renewal forecast review", "09:30", 60, ["alex", "nina"]),
            ("plant_ol_2", "Fernway Retail — escalation review", "10:30", 45, ["hannah", "alex"]),
            ("plant_ol_3", "Interview: Senior CSM candidate", "11:30", 45, ["lena"]),
            ("plant_ol_4", "Sync: support SLA", "13:00", 30, ["sam"]),
            ("plant_ol_5", "Q1 hiring plan", "13:30", 60, ["lena", "sam"]),
            ("plant_ol_6", "Brightwave renewal prep", "14:30", 60, ["alex", "leo"]),
            ("plant_ol_7", "Customer advisory board planning", "15:30", 60, ["nina", "alex"]),
        ]
        items = [dict(eid="plant_emea", title="EMEA renewals sync", start=self.at(d3, "07:15"), end=self.at(d3, "07:45"),
                      organizer=USER_ID, attendees=["emma"])]
        for eid, title, t, dur, atts in overload:
            s = self.at(d3, t)
            items.append(dict(eid=eid, title=title, start=s, end=s + timedelta(minutes=dur), organizer=USER_ID, attendees=atts))
        group(items)


def default_preferences() -> Preferences:
    return Preferences(
        person_id=USER_ID, focus_goal_hours=10, min_focus_block_min=90, preferred_period="any", buffer_min=10,
        max_meeting_hours_day=5.0, max_meeting_hours_week=20.0,
    )


def build_world(now: datetime, seed: int = 7) -> World:
    b = _Builder(now, seed)
    series = b.build_series()
    b.build_user_oneoffs()
    b.build_colleagues()
    b.plant()
    return World(list(b.people.values()), [default_preferences()], series, b.events, b.planted_days)


def seed_database(session: Session, now: datetime, seed: int = 7) -> dict[str, Any]:
    for model in (Event, Series, Preferences, Person, ReminderSetting, Proposal, AuditEntry, Feedback,
                  TelemetryEvent, StudyResult, AiCallLog, BriefCache):
        session.exec(delete(model))  # type: ignore[call-overload]
    session.commit()
    world = build_world(now, seed)
    session.add_all([*world.people, *world.prefs, *world.series, *world.events])
    session.commit()
    return {
        "people": len(world.people),
        "series": len(world.series),
        "events": len(world.events),
        "planted_days": [d.isoformat() for d in world.business_days],
    }
