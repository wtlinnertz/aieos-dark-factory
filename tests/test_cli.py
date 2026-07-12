"""Tests for the dark-factory CLI."""

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


class TestRunGuard:
    def test_run_is_guarded(self, capsys):
        rc = main(["run", "--initiative", ".", "--manifest", MANIFEST, "--preset", "Enhancement"])
        assert rc == 2
        assert "not yet wired" in capsys.readouterr().err


class TestArgparse:
    def test_no_command_exits(self):
        with pytest.raises(SystemExit):
            main([])

    def test_plan_requires_manifest(self):
        with pytest.raises(SystemExit):
            main(["plan", "--preset", "Enhancement"])
