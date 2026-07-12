"""The autonomous pipeline conductor (ADR-0002, v1.3 Track D).

Walks the freeze-DAG one artifact at a time, running each artifact's
generate/validate lifecycle lights-out through the HarnessDriver facade, then
**parks at the freeze gate** for a human. It drives an artifact to
FREEZE_PENDING and no further -- it has no code path that writes FROZEN. A human
freezes via the console (harness apply_freeze_decision); the conductor detects
the freeze on resume (the ER frozen count advanced) and proceeds to the next
artifact.

"Attended-but-automated with an andon cord" (v1.3): the expensive AI work
(generation, validation, convergence) runs unattended; the human is present only
at freeze gates. Before every artifact the conductor checks the andon
``.aieos/halt`` sentinel and, when wired, the FR-019 lock -- either stands the
run down.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from src.decision_register import DecisionRegister, EntryType
from src.driver import HarnessDriver, LifecycleResult


class ConductorStatus(str, Enum):
    RUNNING = "RUNNING"
    PARKED_AT_GATE = "PARKED_AT_GATE"  # awaiting a human freeze
    ESCALATED = "ESCALATED"  # convergence exhausted, human needed
    HALTED = "HALTED"  # andon sentinel / lost lock -- stand down
    COMPLETED = "COMPLETED"


@dataclass
class ConductorState:
    initiative: str
    order: list[str]
    completed: list[str] = field(default_factory=list)
    status: str = ConductorStatus.RUNNING.value
    current: Optional[str] = None
    frozen_count_at_park: int = 0

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> "ConductorState":
        return cls(**json.loads(text))


def _halt_present(initiative_path: Path) -> bool:
    return (Path(initiative_path) / ".aieos" / "halt").exists()


class Conductor:
    """Crash-resumable conductor over one initiative."""

    def __init__(
        self,
        driver: HarnessDriver,
        initiative_path: Path,
        order: list[str],
        *,
        register: Optional[DecisionRegister] = None,
        state_path: Optional[Path] = None,
        lock_ok: Optional[Callable[[], bool]] = None,
        halt_check: Callable[[Path], bool] = _halt_present,
    ) -> None:
        self._driver = driver
        self._initiative = Path(initiative_path)
        self._order = order
        self._register = register or DecisionRegister(
            self._initiative / ".aieos" / "decision-register.jsonl"
        )
        self._state_path = state_path or (
            self._initiative / ".aieos" / "conductor-state.json"
        )
        # FR-019 lock check (injected). Returns True if we still own the lock.
        self._lock_ok = lock_ok
        self._halt_check = halt_check

    # -- state persistence --------------------------------------------------
    def _load_state(self) -> ConductorState:
        if self._state_path.exists():
            return ConductorState.from_json(self._state_path.read_text())
        return ConductorState(initiative=str(self._initiative), order=list(self._order))

    def _save(self, state: ConductorState) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(state.to_json())

    def _artifact_type(self, node: str) -> str:
        return node.split(":", 1)[1]

    # -- main loop ----------------------------------------------------------
    def run(self) -> ConductorState:
        state = self._load_state()

        # If we were parked, see whether the human froze the parked artifact.
        if state.status == ConductorStatus.PARKED_AT_GATE.value and state.current:
            ls = self._driver.read_layer_state(self._initiative)
            if ls.frozen_count > state.frozen_count_at_park:
                self._register.append(
                    EntryType.RESUME, state.current,
                    {"frozen_count": ls.frozen_count},
                )
                state.completed.append(state.current)
                state.current = None
                state.status = ConductorStatus.RUNNING.value
            else:
                return state  # still waiting on the human

        for node in self._order:
            if node in state.completed:
                continue

            # Andon: stand down if a halt sentinel is present.
            if self._halt_check(self._initiative):
                state.status = ConductorStatus.HALTED.value
                state.current = node
                self._save(state)
                return state

            # FR-019: stand down if we no longer own the initiative lock.
            if self._lock_ok is not None and not self._lock_ok():
                state.status = ConductorStatus.HALTED.value
                state.current = node
                self._save(state)
                return state

            result = self._driver.run_artifact_lifecycle(
                self._artifact_type(node), self._initiative
            )

            if result == LifecycleResult.ESCALATION_NEEDED:
                self._register.append(
                    EntryType.ESCALATION, node,
                    {"reason": "convergence_exhausted"},
                )
                state.status = ConductorStatus.ESCALATED.value
                state.current = node
                self._save(state)
                return state

            # CONVERGED -> broker the freeze gate to a human and park.
            ls = self._driver.read_layer_state(self._initiative)
            self._register.append(
                EntryType.FREEZE_REQUEST, node,
                {"frozen_count_before": ls.frozen_count},
            )
            state.status = ConductorStatus.PARKED_AT_GATE.value
            state.current = node
            state.frozen_count_at_park = ls.frozen_count
            self._save(state)
            return state

        state.status = ConductorStatus.COMPLETED.value
        state.current = None
        self._save(state)
        return state
