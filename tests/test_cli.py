"""Tests for the dark-factory CLI."""
import json

from pathlib import Path

import pytest

from src.cli import main

MANIFEST = str(Path(__file__).parent / "fixtures" / "kit-manifest.yml")


class TestPlan:
    def test_plan_prints_order(self, capsys):
        rc = main(["plan", "--manifest", MANIFEST, "--preset", "Enhancement"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "EEK:KER" in out
        assert "REK:RR" in out

    def test_plan_include_optional(self, capsys):
        main(["plan", "--manifest", MANIFEST, "--preset", "Enhancement", "--include-optional"])
        # Enhancement requires EEK+REK; DKR is EEK-optional
        assert "EEK:DKR" in capsys.readouterr().out

    def test_unknown_preset_errors(self):
        with pytest.raises(KeyError):
            main(["plan", "--manifest", MANIFEST, "--preset", "Nope"])


class TestArgparse:
    def test_no_command_exits(self):
        with pytest.raises(SystemExit):
            main([])

    def test_plan_requires_manifest(self):
        with pytest.raises(SystemExit):
            main(["plan", "--preset", "Enhancement"])


_FAKE_CLI_RUN = '''\
import json, sys
a = sys.argv[1:]
if a[0] == "run-artifact":
    print(json.dumps({"result": "CONVERGED"}))
elif a[0] == "read-state":
    print(json.dumps({"frozen_count": 0}))
'''


class TestRunCommand:
    def test_run_parks_at_gate_via_subprocess(self, tmp_path, capsys):
        fake = tmp_path / "fake.py"
        fake.write_text(_FAKE_CLI_RUN)
        init = tmp_path / "init"
        init.mkdir()
        rc = main([
            "run", "--initiative", str(init), "--manifest", MANIFEST,
            "--preset", "Enhancement", "--aieos-root", str(tmp_path / "kits"),
            "--harness-cmd", f"python3 {fake}",
        ])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["status"] == "PARKED_AT_GATE"
        assert out["current"] == "EEK:KER"

    def test_run_requires_aieos_root(self):
        with pytest.raises(SystemExit):
            main(["run", "--initiative", ".", "--manifest", MANIFEST, "--preset", "Enhancement"])


class TestAndonCommands:
    def _halt(self, tmp_path):
        d = tmp_path / ".aieos"
        d.mkdir(parents=True, exist_ok=True)
        (d / "halt").write_text("{}")

    def test_resume_requires_by(self):
        with pytest.raises(SystemExit):
            main(["resume", "--initiative", "."])

    def test_resume_functional(self, tmp_path, capsys):
        self._halt(tmp_path)
        rc = main(["resume", "--initiative", str(tmp_path), "--by", "Todd"])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["resumed"] is True
        assert not (tmp_path / ".aieos" / "halt").exists()

    def test_resume_nothing_to_resume_exit_1(self, tmp_path, capsys):
        (tmp_path / ".aieos").mkdir(parents=True)
        rc = main(["resume", "--initiative", str(tmp_path), "--by", "Todd"])
        assert rc == 1
        assert json.loads(capsys.readouterr().out)["resumed"] is False

    def test_clear_fault_functional(self, tmp_path, capsys):
        self._halt(tmp_path)
        rc = main(["clear-fault", "--initiative", str(tmp_path), "--by", "Todd", "--note", "x"])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["cleared"] is True
        from src.decision_register import DecisionRegister
        reg = DecisionRegister(tmp_path / ".aieos" / "decision-register.jsonl")
        assert reg.entries()[-1].entry_type == "CLEAR_FAULT"
