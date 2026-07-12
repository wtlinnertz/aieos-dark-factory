"""Bridge the real harness facade to the conductor's HarnessDriver Protocol.

The conductor (src/conductor.py) is written against this repo's own Protocol and
enums (src/driver.py) so it is testable without the harness installed. This
adapter wraps a real, initiative-scoped ``aieos-agent-harness`` HarnessDriver and
presents the Protocol, translating the harness's facade types to this repo's by
structural attributes (never importing harness internals).

Duck contract expected of the wrapped driver (satisfied by the harness facade):
- ``run_artifact(artifact_type: str)`` -> object with ``.name`` in
  {"CONVERGED", "ESCALATION_NEEDED"}  (harness LifecycleResult)
- ``read_layer_state()`` -> object with ``.current_layer``, ``.current_artifact``,
  ``.frozen_count``  (harness ERStateBlock)

Packaging seam (staged): instantiating the adapter with a real harness driver
requires the ``aieos-agent-harness`` package importable at runtime. Until that
packaging is set up, the adapter is exercised with a fake in tests; the duck
contract is what the real driver already satisfies (``run_artifact`` added to the
harness facade 2026-07-12).
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from src.driver import FreezeGateDecision, FreezeResult, LayerState, LifecycleResult


class _HarnessLike(Protocol):
    def run_artifact(self, artifact_type: str): ...
    def read_layer_state(self): ...


class HarnessDriverAdapter:
    """Adapts an initiative-scoped harness HarnessDriver to the Protocol.

    ``initiative_path`` is accepted on the Protocol methods for interface
    symmetry but ignored -- the wrapped harness driver is already bound to its
    initiative at construction.
    """

    def __init__(self, harness_driver: _HarnessLike) -> None:
        self._h = harness_driver

    def run_artifact_lifecycle(
        self, artifact_type: str, initiative_path: Path
    ) -> LifecycleResult:
        result = self._h.run_artifact(artifact_type)
        # Translate across the package boundary by enum member name.
        return LifecycleResult[result.name]

    def read_layer_state(self, initiative_path: Path) -> LayerState:
        s = self._h.read_layer_state()
        return LayerState(
            current_layer=getattr(s, "current_layer", ""),
            current_artifact=getattr(s, "current_artifact", ""),
            frozen_count=getattr(s, "frozen_count", 0),
        )

    def apply_freeze_decision(self, decision: FreezeGateDecision) -> FreezeResult:
        # The dark factory NEVER writes FROZEN (ADR-0002). Freezing is a human
        # action through the console/harness, not the conductor. Present on the
        # Protocol for completeness; refusing here enforces the invariant.
        raise NotImplementedError(
            "the dark factory never writes FROZEN; freeze via the console/harness"
        )
