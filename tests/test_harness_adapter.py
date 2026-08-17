"""Tests for the HarnessDriverAdapter (real-harness wiring boundary)."""


import pytest

from src.driver import DecisionOutcome, FreezeGateDecision, LifecycleResult
from src.harness_adapter import HarnessDriverAdapter


class _HResult:
    """Stand-in for the harness's (different) LifecycleResult enum member."""

    def __init__(self, name):
        self.name = name


class _HState:
    def __init__(self, layer, artifact, frozen):
        self.current_layer = layer
        self.current_artifact = artifact
        self.frozen_count = frozen


class FakeHarness:
    def __init__(self, result_name="CONVERGED", state=None):
        self._result_name = result_name
        self._state = state or _HState("Layer 4", "EEK:PRD", 2)
        self.calls = []

    def run_artifact(self, artifact_type):
        self.calls.append(artifact_type)
        return _HResult(self._result_name)

    def read_layer_state(self):
        return self._state


class TestTranslation:
    def test_converged_translates(self, tmp_path):
        a = HarnessDriverAdapter(FakeHarness("CONVERGED"))
        assert a.run_artifact_lifecycle("PRD", tmp_path) == LifecycleResult.CONVERGED

    def test_escalation_translates(self, tmp_path):
        a = HarnessDriverAdapter(FakeHarness("ESCALATION_NEEDED"))
        assert a.run_artifact_lifecycle("PRD", tmp_path) == LifecycleResult.ESCALATION_NEEDED

    def test_passes_artifact_type_through(self, tmp_path):
        h = FakeHarness()
        HarnessDriverAdapter(h).run_artifact_lifecycle("SAD", tmp_path)
        assert h.calls == ["SAD"]

    def test_layer_state_translates(self, tmp_path):
        a = HarnessDriverAdapter(FakeHarness(state=_HState("Layer 5", "REK:RER", 7)))
        ls = a.read_layer_state(tmp_path)
        assert ls.current_layer == "Layer 5"
        assert ls.current_artifact == "REK:RER"
        assert ls.frozen_count == 7


class TestNeverFreezes:
    def test_apply_freeze_decision_refused(self, tmp_path):
        a = HarnessDriverAdapter(FakeHarness())
        decision = FreezeGateDecision(
            artifact_id="EEK:PRD", outcome=DecisionOutcome.APPROVE,
            content_hash="h", decided_by="todd",
        )
        with pytest.raises(NotImplementedError, match="never writes FROZEN"):
            a.apply_freeze_decision(decision)


class TestConductorUsesAdapter:
    def test_adapter_drives_conductor(self, tmp_path):
        # End-to-end: the conductor runs against the adapter + a fake harness.
        from src.conductor import Conductor, ConductorStatus

        adapter = HarnessDriverAdapter(FakeHarness("CONVERGED", _HState("L4", "EEK:KER", 0)))
        state = Conductor(adapter, tmp_path, ["EEK:KER"]).run()
        assert state.status == ConductorStatus.PARKED_AT_GATE.value
        assert state.current == "EEK:KER"
