"""Tests for andon resume / clear-fault (ADR-0004)."""

import pytest

from src.andon import clear_fault, halt_present, resume
from src.decision_register import DecisionRegister


def _halt(tmp_path):
    d = tmp_path / ".aieos"
    d.mkdir(parents=True, exist_ok=True)
    (d / "halt").write_text('{"reason":"stale_lock_takeover"}')


def _register(tmp_path):
    return DecisionRegister(tmp_path / ".aieos" / "decision-register.jsonl")


class TestResume:
    def test_clears_sentinel_and_records(self, tmp_path):
        _halt(tmp_path)
        assert halt_present(tmp_path) is True
        assert resume(tmp_path, "Todd") is True
        assert halt_present(tmp_path) is False
        entries = _register(tmp_path).entries()
        assert entries[-1].entry_type == "RESUME"
        assert entries[-1].payload["cleared_by"] == "Todd"

    def test_no_halt_returns_false_and_records_nothing(self, tmp_path):
        (tmp_path / ".aieos").mkdir(parents=True)
        assert resume(tmp_path, "Todd") is False
        assert _register(tmp_path).entries() == []

    def test_requires_cleared_by(self, tmp_path):
        _halt(tmp_path)
        with pytest.raises(ValueError, match="cleared_by"):
            resume(tmp_path, "  ")

    def test_never_freezes(self, tmp_path):
        # resume must not write any FROZEN status anywhere; it only clears the
        # sentinel + records a RESUME. (No sdlc artifacts are touched.)
        _halt(tmp_path)
        resume(tmp_path, "Todd")
        assert not (tmp_path / "docs").exists()


class TestClearFault:
    def test_records_clear_and_removes_sentinel(self, tmp_path):
        _halt(tmp_path)
        assert clear_fault(tmp_path, "Todd", note="investigated") is True
        assert halt_present(tmp_path) is False
        entries = _register(tmp_path).entries()
        assert entries[-1].entry_type == "CLEAR_FAULT"
        assert entries[-1].payload["note"] == "investigated"

    def test_records_even_without_sentinel(self, tmp_path):
        (tmp_path / ".aieos").mkdir(parents=True)
        # governance clear is recorded regardless; sentinel_removed False
        assert clear_fault(tmp_path, "Todd") is False
        assert _register(tmp_path).entries()[-1].entry_type == "CLEAR_FAULT"

    def test_requires_cleared_by(self, tmp_path):
        with pytest.raises(ValueError, match="cleared_by"):
            clear_fault(tmp_path, "")


class TestChainIntegrity:
    def test_register_chain_valid_after_andon(self, tmp_path):
        _halt(tmp_path)
        clear_fault(tmp_path, "Todd")
        _halt(tmp_path)
        resume(tmp_path, "Todd")
        assert _register(tmp_path).verify_chain() is True


from src.andon import Severity, trip
from src.summon import LogSummoner


class TestTrip:
    def test_writes_halt_records_and_summons(self, tmp_path):
        summoner = LogSummoner()
        payload = trip(
            tmp_path, "invariant_failed", Severity.FAULTED,
            summoner=summoner, details={"gate": "freeze_before_promote"},
        )
        assert payload["severity"] == "FAULTED"
        assert halt_present(tmp_path) is True
        entry = _register(tmp_path).entries()[-1]
        assert entry.entry_type == "HALT"
        assert entry.payload["severity"] == "FAULTED"
        assert summoner.summons[-1]["reason"] == "invariant_failed"

    def test_halted_severity_is_resumable(self, tmp_path):
        trip(tmp_path, "budget_watch", Severity.HALTED)
        assert halt_present(tmp_path) is True
        # a HALTED trip is cleared by resume
        assert resume(tmp_path, "Todd") is True

    def test_trip_without_summoner_ok(self, tmp_path):
        trip(tmp_path, "x", Severity.HALTED)
        assert halt_present(tmp_path) is True

    def test_chain_valid_after_trip_and_resume(self, tmp_path):
        trip(tmp_path, "x", Severity.HALTED)
        resume(tmp_path, "Todd")
        assert _register(tmp_path).verify_chain() is True


class TestTripStatusWriter:
    def test_trip_writes_artifact_status(self, tmp_path):
        writes = []
        trip(
            tmp_path, "invariant_failed", Severity.FAULTED,
            artifact_id="EEK:SAD",
            status_writer=lambda aid, st: writes.append((aid, st)),
        )
        assert writes == [("EEK:SAD", "FAULTED")]

    def test_trip_without_artifact_skips_status_write(self, tmp_path):
        writes = []
        trip(tmp_path, "x", Severity.HALTED, status_writer=lambda a, s: writes.append((a, s)))
        assert writes == []  # no artifact_id -> no status write


from datetime import UTC, datetime

from src.andon import check_liveness


def _state_with_heartbeat(tmp_path, hb: str):
    import json
    d = tmp_path / ".aieos"
    d.mkdir(parents=True, exist_ok=True)
    (d / "conductor-state.json").write_text(json.dumps({"heartbeat": hb}))


class TestLiveness:
    T = datetime(2026, 7, 12, 12, 0, 0, tzinfo=UTC)

    def test_trips_when_stale(self, tmp_path):
        _state_with_heartbeat(tmp_path, "2026-07-12T11:00:00Z")  # 1h old
        assert check_liveness(tmp_path, 300, now=self.T) is True
        assert halt_present(tmp_path) is True
        assert _register(tmp_path).entries()[-1].entry_type == "HALT"

    def test_ok_when_fresh(self, tmp_path):
        _state_with_heartbeat(tmp_path, "2026-07-12T11:59:00Z")  # 60s old
        assert check_liveness(tmp_path, 300, now=self.T) is False
        assert halt_present(tmp_path) is False

    def test_no_state_returns_false(self, tmp_path):
        assert check_liveness(tmp_path, 300, now=self.T) is False

    def test_no_heartbeat_returns_false(self, tmp_path):
        import json
        d = tmp_path / ".aieos"
        d.mkdir(parents=True)
        (d / "conductor-state.json").write_text(json.dumps({}))
        assert check_liveness(tmp_path, 300, now=self.T) is False
