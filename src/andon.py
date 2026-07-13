"""Andon resume / clear-fault (ADR-0004) -- the human stand-up after a halt.

When the conductor stands a run down it writes the ``.aieos/halt`` sentinel and
marks artifacts HALTED (clean stop) or FAULTED (governance breach). A human
brings the run back with a **positive signal**:

- ``resume`` clears a HALTED run: remove the sentinel, record a RESUME entry.
- ``clear_fault`` clears a FAULTED run: record a CLEAR_FAULT entry (a governance
  breach needs a *recorded* human clear before resuming), then remove the sentinel.

Both route through the append-only, hash-chained Decision Register and require a
``cleared_by`` identity. **A resume/clear is NOT a freeze** -- it never touches
``apply_freeze_decision`` and never writes ``FROZEN``. That separation is the
whole point: the andon must never become a backdoor to promotion.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from src.decision_register import DecisionRegister, EntryType
from src.summon import Summoner


class Severity(str, Enum):
    HALTED = "HALTED"   # clean stop, resumable on clear
    FAULTED = "FAULTED"  # governance breach, needs a recorded human clear


def _halt_path(initiative_path: Path) -> Path:
    return Path(initiative_path) / ".aieos" / "halt"


def _register_for(initiative_path: Path, register: Optional[DecisionRegister]) -> DecisionRegister:
    return register or DecisionRegister(
        Path(initiative_path) / ".aieos" / "decision-register.jsonl"
    )


def halt_present(initiative_path: Path) -> bool:
    return _halt_path(initiative_path).exists()


def resume(
    initiative_path: Path,
    cleared_by: str,
    *,
    register: Optional[DecisionRegister] = None,
    note: str = "",
) -> bool:
    """Clear a HALTED run: remove ``.aieos/halt`` and record a RESUME signal.

    Returns True if a halt was present and cleared; False if there was nothing to
    resume. Raises ``ValueError`` if ``cleared_by`` is empty -- a resume requires
    an accountable human.
    """
    if not (cleared_by and cleared_by.strip()):
        raise ValueError("resume requires a non-empty cleared_by identity")
    halt = _halt_path(initiative_path)
    if not halt.exists():
        return False
    halt.unlink()
    _register_for(initiative_path, register).append(
        EntryType.RESUME,
        "INITIATIVE",
        {"action": "resume", "cleared_by": cleared_by, "note": note},
    )
    return True


def clear_fault(
    initiative_path: Path,
    cleared_by: str,
    *,
    register: Optional[DecisionRegister] = None,
    note: str = "",
) -> bool:
    """Clear a FAULTED run: record a CLEAR_FAULT signal, then remove the sentinel.

    A governance breach requires a recorded human clear, so the Decision Register
    entry is written unconditionally (even if the sentinel is already gone). The
    entry is recorded BEFORE the sentinel is removed so the audit trail can never
    lag the action. Returns True if a sentinel was present and removed.
    """
    if not (cleared_by and cleared_by.strip()):
        raise ValueError("clear_fault requires a non-empty cleared_by identity")
    _register_for(initiative_path, register).append(
        EntryType.CLEAR_FAULT,
        "INITIATIVE",
        {"action": "clear_fault", "cleared_by": cleared_by, "note": note},
    )
    halt = _halt_path(initiative_path)
    if halt.exists():
        halt.unlink()
        return True
    return False


def trip(
    initiative_path: Path,
    reason: str,
    severity: Severity,
    *,
    register: Optional[DecisionRegister] = None,
    summoner: Optional[Summoner] = None,
    details: Optional[dict] = None,
) -> dict:
    """Stand a run down (andon trip): write ``.aieos/halt``, record a HALT entry,
    and summon a human. HALTED = clean stop (resumable via ``resume``); FAULTED =
    governance breach (needs ``clear_fault``). Never a freeze -- it never routes
    through ``apply_freeze_decision``. Returns the halt payload.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "event": "trip",
        "reason": reason,
        "severity": severity.value,
        "at": now,
        "details": details or {},
    }
    halt = _halt_path(initiative_path)
    halt.parent.mkdir(parents=True, exist_ok=True)
    halt.write_text(json.dumps(payload, indent=2))
    _register_for(initiative_path, register).append(
        EntryType.HALT,
        "INITIATIVE",
        {"reason": reason, "severity": severity.value},
    )
    if summoner is not None:
        summoner.summon(payload)
    return payload
