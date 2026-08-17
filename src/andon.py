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
from collections.abc import Callable
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from src.decision_register import DecisionRegister, EntryType
from src.summon import Summoner


class Severity(str, Enum):
    HALTED = "HALTED"   # clean stop, resumable on clear
    FAULTED = "FAULTED"  # governance breach, needs a recorded human clear


def _halt_path(initiative_path: Path) -> Path:
    return Path(initiative_path) / ".aieos" / "halt"


def _register_for(initiative_path: Path, register: DecisionRegister | None) -> DecisionRegister:
    return register or DecisionRegister(
        Path(initiative_path) / ".aieos" / "decision-register.jsonl"
    )


def halt_present(initiative_path: Path) -> bool:
    return _halt_path(initiative_path).exists()


def resume(
    initiative_path: Path,
    cleared_by: str,
    *,
    register: DecisionRegister | None = None,
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
    register: DecisionRegister | None = None,
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
    register: DecisionRegister | None = None,
    summoner: Summoner | None = None,
    details: dict | None = None,
    artifact_id: str | None = None,
    status_writer: Callable[[str, str], None] | None = None,
) -> dict:
    """Stand a run down (andon trip): write ``.aieos/halt``, record a HALT entry,
    and summon a human. HALTED = clean stop (resumable via ``resume``); FAULTED =
    governance breach (needs ``clear_fault``). Never a freeze -- it never routes
    through ``apply_freeze_decision``. Returns the halt payload.
    """
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "event": "trip",
        "reason": reason,
        "severity": severity.value,
        "at": now,
        "details": details or {},
    }
    halt = _halt_path(initiative_path)
    halt.parent.mkdir(parents=True, exist_ok=True)
    halt.write_text(json.dumps(payload, indent=2), encoding="utf-8", newline="\n")
    _register_for(initiative_path, register).append(
        EntryType.HALT,
        "INITIATIVE",
        {"reason": reason, "severity": severity.value},
    )
    # Reflect the fault on the artifact's canonical Document Control status
    # (HALTED/FAULTED) via the harness writer, when an artifact + writer are given.
    if artifact_id and status_writer is not None:
        status_writer(artifact_id, severity.value)
    if summoner is not None:
        summoner.summon(payload)
    return payload


def _parse_ts(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def check_liveness(
    initiative_path: Path,
    max_idle_seconds: int,
    *,
    now: datetime | None = None,
    register: DecisionRegister | None = None,
    summoner: Summoner | None = None,
) -> bool:
    """Silent-failure backstop: trip HALTED if the conductor has gone quiet.

    Reads the conductor state's ``heartbeat`` (refreshed on every step). If more
    than ``max_idle_seconds`` have elapsed since it, the run is presumed stuck --
    stand it down (HALTED, resumable) and summon. Returns True if it tripped.
    Returns False when there is no state/heartbeat or the run is still live.
    """
    now = now or datetime.now(UTC)
    state_path = Path(initiative_path) / ".aieos" / "conductor-state.json"
    if not state_path.exists():
        return False
    data = json.loads(state_path.read_text(encoding="utf-8"))
    hb = data.get("heartbeat")
    if not hb:
        return False
    idle = (now - _parse_ts(hb)).total_seconds()
    if idle <= max_idle_seconds:
        return False
    trip(
        initiative_path,
        f"liveness_timeout: idle {int(idle)}s > {max_idle_seconds}s",
        Severity.HALTED,
        register=register,
        summoner=summoner,
        details={"idle_seconds": int(idle)},
    )
    return True
