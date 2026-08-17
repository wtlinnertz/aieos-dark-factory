"""FR-014 slice 4: the conductor calibration precondition (ratified decision 6).

An UNATTENDED walk refuses to start if any validator on the remaining path
lacks a fresh calibration lock -- before a single provider call, so refusal
costs nothing. Attended runs warn and proceed: a human at the keyboard accepts
the risk. A missing lock is stale by definition; unattended trust arrives
per-validator, as calibration coverage does.
"""

from __future__ import annotations

import json

from src.conductor import Conductor, ConductorStatus
from src.driver import CalibrationCheck
from tests.test_conductor import FakeDriver

ORDER = ["EEK:KER", "EEK:PRD", "EEK:SAD"]


class RecordingCheck:
    """Injected calibration check: scripted freshness per validator."""

    def __init__(self, stale: set[str] | None = None):
        self.stale = stale or set()
        self.calls: list[tuple[str, str]] = []

    def __call__(self, validator: str, kit_abbr: str) -> CalibrationCheck:
        self.calls.append((validator, kit_abbr))
        if validator in self.stale:
            return CalibrationCheck(fresh=False, reason="stale_prompt")
        return CalibrationCheck(fresh=True, reason="")


def _conductor(tmp_path, driver, **kw):
    return Conductor(driver, tmp_path, ORDER, **kw)


def _register_entries(tmp_path):
    path = tmp_path / ".aieos" / "decision-register.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


class TestUnattendedRefusal:
    def test_stale_validator_refuses_before_any_spend(self, tmp_path):
        d = FakeDriver()
        check = RecordingCheck(stale={"sad-validator"})
        state = _conductor(tmp_path, d, calibration_check=check).run()
        assert state.status == ConductorStatus.CALIBRATION_REFUSED.value
        assert d.lifecycle_calls == [], "refusal must precede any provider call"
        assert d.freeze_calls == []

    def test_refusal_is_registered_with_the_issues(self, tmp_path):
        d = FakeDriver()
        check = RecordingCheck(stale={"sad-validator", "prd-validator"})
        _conductor(tmp_path, d, calibration_check=check).run()
        entries = _register_entries(tmp_path)
        assert len(entries) == 1
        assert entries[0]["entry_type"] == "CALIBRATION_REFUSED"
        issues = entries[0]["payload"]["issues"]
        assert {i["validator"] for i in issues} == {"sad-validator", "prd-validator"}
        assert all(i["kit"] == "EEK" for i in issues)

    def test_refusal_summons(self, tmp_path):
        summons = []

        class Summoner:
            def summon(self, payload):
                summons.append(payload)

        d = FakeDriver()
        check = RecordingCheck(stale={"ker-validator"})
        _conductor(
            tmp_path, d, calibration_check=check, summoner=Summoner()
        ).run()
        assert summons and summons[0]["event"] == "calibration_refused"

    def test_missing_lock_shaped_result_refuses(self, tmp_path):
        # Anything not fresh refuses -- including 'no lock exists yet', the
        # day-one state of every kit.
        d = FakeDriver()
        state = _conductor(
            tmp_path, d,
            calibration_check=lambda v, k: CalibrationCheck(False, "missing_lock"),
        ).run()
        assert state.status == ConductorStatus.CALIBRATION_REFUSED.value
        assert d.lifecycle_calls == []


class TestFreshPathProceeds:
    def test_all_fresh_walks_normally(self, tmp_path):
        d = FakeDriver()
        check = RecordingCheck()
        state = _conductor(tmp_path, d, calibration_check=check).run()
        # Normal walk: first artifact converges and parks at the freeze gate.
        assert state.status == ConductorStatus.PARKED_AT_GATE.value
        assert d.lifecycle_calls == ["KER"]

    def test_validators_deduplicated_one_check_each(self, tmp_path):
        d = FakeDriver()
        check = RecordingCheck()
        Conductor(
            d, tmp_path, ["EEK:SAD", "QAK:SAD", "EEK:TDD"],
            calibration_check=check,
        ).run()
        # SAD appears twice but sad-validator is checked once (first kit wins).
        assert sorted(c[0] for c in check.calls) == ["sad-validator", "tdd-validator"]

    def test_completed_nodes_are_not_rechecked(self, tmp_path):
        d = FakeDriver()
        check = RecordingCheck(stale={"ker-validator"})
        # KER already completed in a prior run: its stale validator is off the path.
        state_path = tmp_path / ".aieos" / "conductor-state.json"
        state_path.parent.mkdir(parents=True)
        state_path.write_text(json.dumps({
            "initiative": str(tmp_path),
            "order": ORDER,
            "completed": ["EEK:KER"],
            "current": None,
            "status": "RUNNING",
            "frozen_count_at_park": 0,
            "heartbeat": "",
        }))
        state = _conductor(tmp_path, d, calibration_check=check).run()
        assert state.status == ConductorStatus.PARKED_AT_GATE.value
        assert ("ker-validator", "EEK") not in check.calls

    def test_no_check_injected_gate_is_disabled(self, tmp_path):
        d = FakeDriver()
        state = _conductor(tmp_path, d).run()
        assert state.status == ConductorStatus.PARKED_AT_GATE.value


class TestAttendedWarns:
    def test_attended_warns_and_proceeds(self, tmp_path):
        d = FakeDriver()
        check = RecordingCheck(stale={"sad-validator"})
        state = _conductor(
            tmp_path, d, calibration_check=check, attended=True
        ).run()
        assert state.status == ConductorStatus.PARKED_AT_GATE.value
        assert d.lifecycle_calls == ["KER"]
        entries = _register_entries(tmp_path)
        assert entries[0]["entry_type"] == "CALIBRATION_WARNING"
        assert entries[0]["payload"]["attended"] is True


class TestSubprocessCheckCalibration:
    def _driver(self, returncode, stdout):
        from src.subprocess_driver import SubprocessHarnessDriver

        calls = []

        class Proc:
            def __init__(self):
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = ""

        def runner(cmd, **kw):
            calls.append(cmd)
            return Proc()

        from pathlib import Path

        d = SubprocessHarnessDriver(["harness"], Path("."), runner=runner)
        return d, calls

    def test_fresh_exit_0(self, tmp_path):
        d, calls = self._driver(0, json.dumps({"fresh": True, "reason": ""}))
        result = d.check_calibration("sad-validator", tmp_path / "calibration.lock")
        assert result.fresh is True
        argv = calls[0]
        assert argv[:3] == ["harness", "calibrate", "--check-only"]
        assert "--validator" in argv and "sad-validator" in argv

    def test_stale_exit_4_is_an_answer_not_an_error(self, tmp_path):
        d, _ = self._driver(4, json.dumps({"fresh": False, "reason": "missing_lock"}))
        result = d.check_calibration("sad-validator", tmp_path / "calibration.lock")
        assert result.fresh is False
        assert result.reason == "missing_lock"

    def test_other_exit_raises(self, tmp_path):
        from src.subprocess_driver import SubprocessHarnessError

        d, _ = self._driver(2, "")
        try:
            d.check_calibration("sad-validator", tmp_path / "calibration.lock")
            raise AssertionError("expected SubprocessHarnessError")
        except SubprocessHarnessError:
            pass


class TestAdapterPassthrough:
    def test_wrapped_driver_without_op_is_not_fresh(self, tmp_path):
        from src.harness_adapter import HarnessDriverAdapter

        class BareHarness:
            def run_artifact(self, artifact_type):  # pragma: no cover
                raise AssertionError("not used")

            def read_layer_state(self):  # pragma: no cover
                raise AssertionError("not used")

        adapter = HarnessDriverAdapter(BareHarness())
        result = adapter.check_calibration("sad-validator", tmp_path / "lock")
        assert result.fresh is False
        assert "check_unavailable" in result.reason
