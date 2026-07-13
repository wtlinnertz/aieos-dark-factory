"""Tests for the SubprocessHarnessDriver (packaging seam over the harness CLI)."""

import json

import pytest

from src.driver import DecisionOutcome, FreezeGateDecision, LifecycleResult
from src.subprocess_driver import SubprocessHarnessDriver, SubprocessHarnessError


class _Proc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _runner(proc, sink=None):
    def run(cmd, capture_output=True, text=True, cwd=None):
        if sink is not None:
            sink.append((cmd, cwd))
        return proc
    return run


class TestUnitWithFakeRunner:
    def test_run_artifact_parses_result(self, tmp_path):
        d = SubprocessHarnessDriver(
            ["harness"], tmp_path, runner=_runner(_Proc(stdout=json.dumps({"result": "CONVERGED"}))),
        )
        assert d.run_artifact_lifecycle("PRD", tmp_path) == LifecycleResult.CONVERGED

    def test_run_artifact_escalation(self, tmp_path):
        d = SubprocessHarnessDriver(
            ["harness"], tmp_path,
            runner=_runner(_Proc(stdout=json.dumps({"result": "ESCALATION_NEEDED"}))),
        )
        assert d.run_artifact_lifecycle("PRD", tmp_path) == LifecycleResult.ESCALATION_NEEDED

    def test_invokes_argv_no_shell(self, tmp_path):
        sink = []
        d = SubprocessHarnessDriver(
            ["python", "-m", "src.cli"], tmp_path / "kits",
            runner=_runner(_Proc(stdout='{"result": "CONVERGED"}'), sink),
        )
        d.run_artifact_lifecycle("SAD", tmp_path / "init")
        cmd, _cwd = sink[0]
        assert cmd[:3] == ["python", "-m", "src.cli"]
        assert "run-artifact" in cmd and "--type" in cmd and "SAD" in cmd

    def test_read_state_parses(self, tmp_path):
        d = SubprocessHarnessDriver(
            ["harness"], tmp_path,
            runner=_runner(_Proc(stdout=json.dumps({"current_layer": "L4", "frozen_count": 3}))),
        )
        ls = d.read_layer_state(tmp_path)
        assert ls.frozen_count == 3

    def test_nonzero_exit_raises(self, tmp_path):
        d = SubprocessHarnessDriver(
            ["harness"], tmp_path, runner=_runner(_Proc(returncode=1, stderr="boom")),
        )
        with pytest.raises(SubprocessHarnessError, match="boom"):
            d.read_layer_state(tmp_path)

    def test_bad_json_raises(self, tmp_path):
        d = SubprocessHarnessDriver(
            ["harness"], tmp_path, runner=_runner(_Proc(stdout="not json")),
        )
        with pytest.raises(SubprocessHarnessError, match="non-JSON"):
            d.read_layer_state(tmp_path)

    def test_never_freezes(self, tmp_path):
        d = SubprocessHarnessDriver(["harness"], tmp_path)
        with pytest.raises(NotImplementedError):
            d.apply_freeze_decision(
                FreezeGateDecision("A", DecisionOutcome.APPROVE, "h", "todd")
            )


# --- Real subprocess integration against a fake harness CLI --------------------

_FAKE_CLI = '''\
import json, sys
args = sys.argv[1:]
cmd = args[0]
if cmd == "run-artifact":
    print(json.dumps({"result": "CONVERGED"}))
elif cmd == "read-state":
    print(json.dumps({"current_layer": "L4", "current_artifact": "EEK:KER", "frozen_count": 0}))
else:
    print(json.dumps({"error": "unknown"})); sys.exit(2)
'''


class TestRealSubprocess:
    def test_end_to_end_via_real_subprocess(self, tmp_path):
        fake = tmp_path / "fake_harness.py"
        fake.write_text(_FAKE_CLI)
        d = SubprocessHarnessDriver(["python3", str(fake)], tmp_path / "kits")
        # real subprocess, real JSON parse
        assert d.run_artifact_lifecycle("KER", tmp_path) == LifecycleResult.CONVERGED
        assert d.read_layer_state(tmp_path).frozen_count == 0

    def test_conductor_runs_over_real_subprocess(self, tmp_path):
        from src.conductor import Conductor, ConductorStatus

        fake = tmp_path / "fake_harness.py"
        fake.write_text(_FAKE_CLI)
        init = tmp_path / "init"
        init.mkdir()
        d = SubprocessHarnessDriver(["python3", str(fake)], tmp_path / "kits")
        state = Conductor(d, init, ["EEK:KER"]).run()
        assert state.status == ConductorStatus.PARKED_AT_GATE.value
        assert state.current == "EEK:KER"


class TestMarkStatus:
    def test_mark_status_invokes_harness(self, tmp_path):
        sink = []
        def runner(cmd, capture_output=True, text=True, cwd=None):
            sink.append(cmd)
            return _Proc(stdout=json.dumps({"status": "FAULTED", "artifact": "A", "path": "p"}))
        d = SubprocessHarnessDriver(["harness"], tmp_path, runner=runner)
        d.mark_status("EEK:PRD", "FAULTED", tmp_path / "init")
        cmd = sink[0]
        assert "mark-status" in cmd and "--status" in cmd and "FAULTED" in cmd
        assert "EEK:PRD" in cmd
