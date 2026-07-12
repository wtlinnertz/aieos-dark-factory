"""The HarnessDriver boundary -- the ONLY surface the dark factory depends on.

aieos-dark-factory is a pure control plane (ADR-0002). It imports this facade
contract and nothing from the harness internals -- not convergence, state, or
invariants. Modelled here as a typing.Protocol so the conductor codes against
the interface; the real harness (aieos-agent-harness src/driver.py::HarnessDriver)
satisfies it, and tests use a fake.

Integration seam (staged): the harness's current facade takes AgentRequests for
run_artifact_lifecycle; a thin harness-side adapter will expose the
artifact-type-level signature the conductor needs here. Until then this Protocol
is the contract both sides target.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable


class LifecycleResult(Enum):
    CONVERGED = "CONVERGED"
    ESCALATION_NEEDED = "ESCALATION_NEEDED"


class DecisionOutcome(Enum):
    APPROVE = "APPROVE"
    APPROVE_WITH_CONDITIONS = "APPROVE_WITH_CONDITIONS"
    BLOCK = "BLOCK"
    REMEDIATE_AND_RETRY = "REMEDIATE_AND_RETRY"
    REQUIRE_REDESIGN = "REQUIRE_REDESIGN"


@dataclass
class LayerState:
    """The subset of the ER state block the conductor reads (facade op 2)."""

    current_layer: str = ""
    current_artifact: str = ""
    frozen_count: int = 0


@dataclass
class FreezeGateDecision:
    """Mirror of the harness FreezeGateDecision. The conductor NEVER constructs
    an approving one -- it only ever brokers a request to a human. Present on the
    boundary for type-completeness."""

    artifact_id: str
    outcome: DecisionOutcome
    content_hash: str
    decided_by: str
    auto_freeze_attempted: bool = False


@dataclass
class FreezeResult:
    artifact_id: str
    status: str
    decided_by: str
    frozen_count: Optional[int] = None


@runtime_checkable
class HarnessDriver(Protocol):
    """The 3-op facade (ADR-0002). The conductor uses only the first two; it has
    no code path that writes FROZEN, so it never calls apply_freeze_decision."""

    def run_artifact_lifecycle(
        self, artifact_type: str, initiative_path: Path
    ) -> LifecycleResult: ...

    def read_layer_state(self, initiative_path: Path) -> LayerState: ...

    def apply_freeze_decision(
        self, decision: FreezeGateDecision
    ) -> FreezeResult: ...
