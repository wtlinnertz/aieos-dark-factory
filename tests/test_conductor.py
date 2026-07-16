"""Tests for the conductor state machine (walk / gate-park / escalate / halt / resume)."""



from src.conductor import Conductor, ConductorStatus
from src.decision_register import DecisionRegister
from src.driver import LayerState, LifecycleResult


class FakeDriver:
    """Test double for the HarnessDriver facade.

    - ``results``: per-artifact-type LifecycleResult (default CONVERGED).
    - ``frozen_count``: the ER frozen count read_layer_state returns; a test
      bumps it to simulate a human freezing the parked artifact.
    - records calls so tests can assert apply_freeze_decision is NEVER called.
    """

    def __init__(self, results=None, frozen_count=0):
        self.results = results or {}
        self.frozen_count = frozen_count
        self.lifecycle_calls = []
        self.freeze_calls = []

    def run_artifact_lifecycle(self, artifact_type, initiative_path):
        self.lifecycle_calls.append(artifact_type)
        return self.results.get(artifact_type, LifecycleResult.CONVERGED)

    def read_layer_state(self, initiative_path):
        return LayerState(frozen_count=self.frozen_count)

    def apply_freeze_decision(self, decision):  # pragma: no cover - must never run
        self.freeze_calls.append(decision)
        raise AssertionError("conductor must never write FROZEN")


ORDER = ["EEK:KER", "EEK:PRD", "EEK:SAD"]


def _conductor(tmp_path, driver, **kw):
    return Conductor(driver, tmp_path, ORDER, **kw)


class TestAlreadyFrozenNodesAreSkipped:
    """G-13: the conductor must walk PAST frozen artifacts, not re-run them.

    Found by the real-AI dogfood 2026-07-15: the conductor decided "is this node
    done?" from its own state file, never from the artifacts. On a real
    initiative every upstream artifact is frozen, so a re-walk regenerated over
    human-approved work. The harness now refuses and returns ALREADY_FROZEN;
    the conductor must honour that and keep going.
    """

    def test_frozen_nodes_are_skipped_and_walk_reaches_the_pending_one(self, tmp_path):
        d = FakeDriver(results={
            "KER": LifecycleResult.ALREADY_FROZEN,
            "PRD": LifecycleResult.ALREADY_FROZEN,
        })
        state = _conductor(tmp_path, d).run()
        # Walked past both frozen nodes and parked at the first real work.
        assert state.status == ConductorStatus.PARKED_AT_GATE.value
        assert state.current == "EEK:SAD"
        assert d.lifecycle_calls == ["KER", "PRD", "SAD"]

    def test_frozen_nodes_do_not_park_at_an_already_cleared_gate(self, tmp_path):
        d = FakeDriver(results={t: LifecycleResult.ALREADY_FROZEN for t in ("KER", "PRD", "SAD")})
        state = _conductor(tmp_path, d).run()
        # Every node frozen => the walk is finished, not parked.
        assert state.status == ConductorStatus.COMPLETED.value
        assert state.current is None

    def test_frozen_nodes_are_recorded_completed_so_a_rewalk_is_free(self, tmp_path):
        d = FakeDriver(results={"KER": LifecycleResult.ALREADY_FROZEN})
        c = _conductor(tmp_path, d)
        c.run()
        assert "EEK:KER" in c.run().completed


class TestParksAtGate:
    def test_fresh_run_parks_at_first_artifact(self, tmp_path):
        d = FakeDriver()
        state = _conductor(tmp_path, d).run()
        assert state.status == ConductorStatus.PARKED_AT_GATE.value
        assert state.current == "EEK:KER"
        assert d.lifecycle_calls == ["KER"]

    def test_never_calls_apply_freeze_decision(self, tmp_path):
        d = FakeDriver()
        _conductor(tmp_path, d).run()
        assert d.freeze_calls == []

    def test_logs_freeze_request_to_register(self, tmp_path):
        d = FakeDriver()
        c = _conductor(tmp_path, d)
        c.run()
        reg = DecisionRegister(tmp_path / ".aieos" / "decision-register.jsonl")
        entries = reg.entries()
        assert entries[-1].entry_type == "FREEZE_REQUEST"
        assert entries[-1].artifact_id == "EEK:KER"
        assert reg.verify_chain() is True


class TestResume:
    def test_resume_blocked_until_human_freezes(self, tmp_path):
        d = FakeDriver(frozen_count=0)
        _conductor(tmp_path, d).run()  # parks at KER
        # human has NOT frozen -> frozen_count unchanged -> still parked, no new work
        d.lifecycle_calls.clear()
        state = _conductor(tmp_path, d).run()
        assert state.status == ConductorStatus.PARKED_AT_GATE.value
        assert state.current == "EEK:KER"
        assert d.lifecycle_calls == []

    def test_resume_advances_after_human_freeze(self, tmp_path):
        d = FakeDriver(frozen_count=0)
        _conductor(tmp_path, d).run()  # parks at KER
        d.frozen_count = 1  # human froze KER
        state = _conductor(tmp_path, d).run()
        assert state.status == ConductorStatus.PARKED_AT_GATE.value
        assert state.current == "EEK:PRD"  # advanced
        assert "EEK:KER" in state.completed

    def test_full_walk_to_completion(self, tmp_path):
        d = FakeDriver(frozen_count=0)
        # Drive the whole order, freezing at each gate.
        for i in range(1, len(ORDER) + 1):
            state = _conductor(tmp_path, d).run()
            if state.status == ConductorStatus.COMPLETED.value:
                break
            d.frozen_count = i  # simulate human freezing the parked artifact
        state = _conductor(tmp_path, d).run()
        assert state.status == ConductorStatus.COMPLETED.value
        assert state.completed == ORDER


class TestEscalation:
    def test_escalation_stops_and_records(self, tmp_path):
        d = FakeDriver(results={"EEK:KER": LifecycleResult.ESCALATION_NEEDED})
        # KER type is "KER"
        d.results = {"KER": LifecycleResult.ESCALATION_NEEDED}
        state = _conductor(tmp_path, d).run()
        assert state.status == ConductorStatus.ESCALATED.value
        assert state.current == "EEK:KER"
        reg = DecisionRegister(tmp_path / ".aieos" / "decision-register.jsonl")
        assert reg.entries()[-1].entry_type == "ESCALATION"


class TestAndonHalt:
    def test_halt_sentinel_stands_down_before_work(self, tmp_path):
        (tmp_path / ".aieos").mkdir(parents=True)
        (tmp_path / ".aieos" / "halt").write_text("{}")
        d = FakeDriver()
        state = _conductor(tmp_path, d).run()
        assert state.status == ConductorStatus.HALTED.value
        assert d.lifecycle_calls == []  # never ran any artifact

    def test_lost_lock_stands_down(self, tmp_path):
        d = FakeDriver()
        state = _conductor(tmp_path, d, lock_ok=lambda: False).run()
        assert state.status == ConductorStatus.HALTED.value
        assert d.lifecycle_calls == []


class TestCrashResumption:
    def test_state_persists_and_reloads(self, tmp_path):
        d = FakeDriver(frozen_count=0)
        _conductor(tmp_path, d).run()  # parks at KER, writes state
        assert (tmp_path / ".aieos" / "conductor-state.json").exists()
        # brand-new Conductor instance (simulates a restart) picks up the state
        d.frozen_count = 1
        state = Conductor(d, tmp_path, ORDER).run()
        assert "EEK:KER" in state.completed
        assert state.current == "EEK:PRD"


from src.summon import LogSummoner  # noqa: E402


class TestConductorSummon:
    def test_summons_on_escalation(self, tmp_path):
        d = FakeDriver(results={"KER": LifecycleResult.ESCALATION_NEEDED})
        summoner = LogSummoner()
        Conductor(d, tmp_path, ["EEK:KER"], summoner=summoner).run()
        assert summoner.summons[-1]["event"] == "escalation"
        assert summoner.summons[-1]["artifact"] == "EEK:KER"

    def test_summons_on_halt_sentinel(self, tmp_path):
        (tmp_path / ".aieos").mkdir(parents=True)
        (tmp_path / ".aieos" / "halt").write_text("{}")
        summoner = LogSummoner()
        Conductor(FakeDriver(), tmp_path, ["EEK:KER"], summoner=summoner).run()
        assert summoner.summons[-1]["event"] == "halt"

    def test_summons_on_lost_lock(self, tmp_path):
        summoner = LogSummoner()
        Conductor(FakeDriver(), tmp_path, ["EEK:KER"], lock_ok=lambda: False, summoner=summoner).run()
        assert summoner.summons[-1]["event"] == "lock_lost"

    def test_no_summoner_is_fine(self, tmp_path):
        d = FakeDriver(results={"KER": LifecycleResult.ESCALATION_NEEDED})
        state = Conductor(d, tmp_path, ["EEK:KER"]).run()
        assert state.status == ConductorStatus.ESCALATED.value


class TestHardTrip:
    def test_driver_failure_faults_and_stands_down(self, tmp_path):
        from src.summon import LogSummoner

        class BoomDriver(FakeDriver):
            def run_artifact_lifecycle(self, artifact_type, initiative_path):
                raise RuntimeError("harness crashed")

        summoner = LogSummoner()
        state = Conductor(BoomDriver(), tmp_path, ["EEK:KER"], summoner=summoner).run()
        assert state.status == ConductorStatus.HALTED.value
        # halt sentinel written + FAULT recorded + summoned
        assert (tmp_path / ".aieos" / "halt").exists()
        reg = DecisionRegister(tmp_path / ".aieos" / "decision-register.jsonl")
        last = reg.entries()[-1]
        assert last.entry_type == "HALT"
        assert last.payload["severity"] == "FAULTED"
        assert summoner.summons[-1]["severity"] == "FAULTED"

    def test_heartbeat_written_on_save(self, tmp_path):
        Conductor(FakeDriver(), tmp_path, ["EEK:KER"]).run()  # parks -> saves
        import json as _j
        data = _j.loads((tmp_path / ".aieos" / "conductor-state.json").read_text())
        assert data["heartbeat"].endswith("Z")
