"""Who asks the boiler for heat, and when that changed. Pure Python, no Home Assistant imports."""
from __future__ import annotations

from collections import deque


class RequestLog:
    def __init__(self, maxlen: int = 30) -> None:
        self.asking: list[str] = []       # rooms asking now
        self.since: str | None = None     # when the set of asking rooms last changed
        self.entries: deque[dict] = deque(maxlen=maxlen)  # oldest first

    def update(self, asking: list[str], reasons: dict[str, str], at: str) -> list[dict]:
        """Record the rooms that started or stopped asking since the last call.

        `reasons` maps a room name to why it decided so; `at` is an ISO time. Returns the new entries
        (empty when the set of rooms did not change).
        """
        started = [r for r in asking if r not in self.asking]
        stopped = [r for r in self.asking if r not in asking]
        self.asking = list(asking)
        new = [{"at": at, "room": room, "event": event, "reason": reasons.get(room, ""), "asking": list(asking)}
               for event, rooms in (("stop", stopped), ("start", started)) for room in rooms]
        self.entries.extend(new)
        if new:
            self.since = at
        return new
