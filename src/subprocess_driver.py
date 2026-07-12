"""Run the conductor against the real harness via a CLI subprocess.

The packaging seam (ADR-0002 boundary, realized with ADR-0003's subprocess
pattern). Both ``aieos-dark-factory`` and ``aieos-agent-harness`` use ``src`` as
their import root, so an in-process ``import src.driver`` from the harness would
collide with this repo's own ``src`` package. Rather than repackage the entire
harness, the conductor reaches the harness through its CLI -- the same
cross-boundary mechanism ADR-0003 chose for the console. This keeps the control
plane strictly free of harness internals: it can only call the published
subcommands.

Implements the HarnessDriver Protocol (src/driver.py) by invoking:
  <harness_cmd> run-artifact --type T --initiative I --aieos-root R   -> {"result": ...}
  <harness_cmd> read-state   --initiative I                           -> {"frozen_count": ...}
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Callable, Optional

from src.driver import FreezeGateDecision, FreezeResult, LayerState, LifecycleResult


class SubprocessHarnessError(RuntimeError):
    """The harness subprocess failed or returned unparseable output."""


class SubprocessHarnessDriver:
    """HarnessDriver Protocol implementation over the harness CLI (subprocess)."""

    def __init__(
        self,
        harness_cmd: list[str],
        aieos_root: Path,
        *,
        cwd: Optional[Path] = None,
        runner: Callable[..., "subprocess.CompletedProcess"] = subprocess.run,
    ) -> None:
        # e.g. harness_cmd = ["python", "-m", "src.cli"] (with cwd=harness repo)
        # or an installed entrypoint ["harness"]. Always an argv list, never a
        # shell string -- no shell injection (ADR-0003 hazard).
        self._cmd = list(harness_cmd)
        self._aieos_root = Path(aieos_root)
        self._cwd = Path(cwd) if cwd is not None else None
        self._runner = runner

    def _invoke(self, args: list[str]) -> dict:
        proc = self._runner(
            self._cmd + args,
            capture_output=True,
            text=True,
            cwd=str(self._cwd) if self._cwd else None,
        )
        if proc.returncode != 0:
            raise SubprocessHarnessError(
                f"harness {args[0]} failed (exit {proc.returncode}): "
                f"{(proc.stderr or '').strip()}"
            )
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise SubprocessHarnessError(
                f"harness {args[0]} returned non-JSON: {proc.stdout[:200]!r}"
            ) from exc

    def run_artifact_lifecycle(
        self, artifact_type: str, initiative_path: Path
    ) -> LifecycleResult:
        data = self._invoke([
            "run-artifact",
            "--type", artifact_type,
            "--initiative", str(initiative_path),
            "--aieos-root", str(self._aieos_root),
        ])
        return LifecycleResult[data["result"]]

    def read_layer_state(self, initiative_path: Path) -> LayerState:
        data = self._invoke(["read-state", "--initiative", str(initiative_path)])
        return LayerState(
            current_layer=data.get("current_layer", ""),
            current_artifact=data.get("current_artifact", ""),
            frozen_count=data.get("frozen_count", 0),
        )

    def apply_freeze_decision(self, decision: FreezeGateDecision) -> FreezeResult:
        raise NotImplementedError(
            "the dark factory never writes FROZEN; freeze via the console/harness"
        )
