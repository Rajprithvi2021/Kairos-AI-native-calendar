"""Injectable clock. Engines never read the system clock directly, so demos and tests can freeze time."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def parse_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("datetime must include a UTC offset")
    return dt.astimezone(UTC)


class Clock:
    def __init__(self) -> None:
        self._frozen: datetime | None = None
        self._offset = timedelta(0)

    def now(self) -> datetime:
        if self._frozen is not None:
            return self._frozen
        return datetime.now(UTC) + self._offset

    @property
    def is_simulated(self) -> bool:
        return self._frozen is not None or self._offset != timedelta(0)

    def freeze(self, at: datetime) -> None:
        self._frozen = at.astimezone(UTC)

    def reset(self) -> None:
        self._frozen = None
        self._offset = timedelta(0)


clock = Clock()
