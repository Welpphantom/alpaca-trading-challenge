"""Breach confirmation for kill switches.

A destructive action fires only after N consecutive VALID breach readings
spanning at least `min_span_seconds`. Invalid readings (failed data sanity)
pause the clock — they neither advance nor reset the breach count, so a data
glitch can never trigger action and never mask a real breach. A valid
non-breach reading resets the count to zero.
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class BreachTracker:
    readings_required: int
    min_span_seconds: float
    _breach_ts: list[datetime] = field(default_factory=list)
    paused: bool = False          # last reading was invalid (data quality)

    def record(self, ts: datetime, breached: bool, valid: bool) -> None:
        if not valid:
            self.paused = True
            return
        self.paused = False
        if breached:
            self._breach_ts.append(ts)
        else:
            self._breach_ts.clear()

    @property
    def confirmed(self) -> bool:
        if len(self._breach_ts) < self.readings_required:
            return False
        span = (self._breach_ts[-1] - self._breach_ts[0]).total_seconds()
        return span >= self.min_span_seconds

    @property
    def breach_count(self) -> int:
        return len(self._breach_ts)
