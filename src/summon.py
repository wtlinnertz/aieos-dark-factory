"""Summon channel for the andon cord (ADR-0004).

When the conductor stands a run down (hard trip) or parks it (soft trip), it
summons a human. The channel is an injectable ``Summoner`` so the mechanism is
testable and the transport is pluggable:

- ``LogSummoner`` (default) records summons in-process — enough for tests, CI,
  and a local run with no email configured.
- ``EmailSummoner`` formats a subject/body and delegates to an injected ``send``
  callable. The v1 target is the existing Gmail integration; wiring that real
  ``send`` is a thin adapter (and PagerDuty/webhook is v1.1, needs OAuth), so it
  is intentionally injected rather than hard-wired here.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable


@runtime_checkable
class Summoner(Protocol):
    def summon(self, payload: dict) -> None: ...


class LogSummoner:
    """Records summons in-process (default; zero external dependencies)."""

    def __init__(self) -> None:
        self.summons: list[dict] = []

    def summon(self, payload: dict) -> None:
        self.summons.append(payload)


def _format(payload: dict) -> tuple[str, str]:
    event = payload.get("event", "andon")
    severity = payload.get("severity", "")
    artifact = payload.get("artifact", payload.get("initiative", ""))
    subject = f"[AIEOS andon] {event} {severity}".strip() + (f" — {artifact}" if artifact else "")
    lines = [f"{k}: {v}" for k, v in payload.items()]
    return subject, "\n".join(lines)


class EmailSummoner:
    """Formats the summon and hands it to an injected ``send(subject, body)``.

    The real transport (Gmail) supplies ``send``; this class owns only the
    message shape, so it is unit-testable without a live mailbox.
    """

    def __init__(self, send: Callable[[str, str], None], to: str = "") -> None:
        self._send = send
        self._to = to

    def summon(self, payload: dict) -> None:
        subject, body = _format(payload)
        if self._to:
            body = f"To: {self._to}\n\n{body}"
        self._send(subject, body)
