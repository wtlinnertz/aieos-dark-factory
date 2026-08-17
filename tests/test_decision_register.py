"""Tests for the append-only hash-chained Decision Register."""

from datetime import UTC, datetime

from src.decision_register import DecisionRegister, EntryType

T0 = datetime(2026, 7, 12, 12, 0, 0, tzinfo=UTC)


class TestAppendAndRead:
    def test_first_entry_links_to_genesis(self, tmp_path):
        reg = DecisionRegister(tmp_path / ".aieos" / "decision-register.jsonl")
        e = reg.append(EntryType.FREEZE_REQUEST, "EEK:PRD", {"gate": "prd"}, now=T0)
        assert e.index == 0
        assert e.prev_hash == "GENESIS"
        assert reg.entries()[0].artifact_id == "EEK:PRD"

    def test_chain_links_forward(self, tmp_path):
        reg = DecisionRegister(tmp_path / "reg.jsonl")
        a = reg.append(EntryType.FREEZE_REQUEST, "EEK:PRD", {}, now=T0)
        b = reg.append(EntryType.ESCALATION, "EEK:SAD", {"reason": "exhausted"}, now=T0)
        assert b.prev_hash == a.entry_hash
        assert b.index == 1

    def test_verify_chain_true_for_valid(self, tmp_path):
        reg = DecisionRegister(tmp_path / "reg.jsonl")
        reg.append(EntryType.FREEZE_REQUEST, "A", {}, now=T0)
        reg.append(EntryType.RESUME, "A", {"by": "todd"}, now=T0)
        reg.append(EntryType.FREEZE_REQUEST, "B", {}, now=T0)
        assert reg.verify_chain() is True

    def test_verify_chain_detects_tampering(self, tmp_path):
        path = tmp_path / "reg.jsonl"
        reg = DecisionRegister(path)
        reg.append(EntryType.FREEZE_REQUEST, "A", {"n": 1}, now=T0)
        reg.append(EntryType.FREEZE_REQUEST, "B", {"n": 2}, now=T0)
        # Tamper with the first entry's payload on disk.
        lines = path.read_text().splitlines()
        lines[0] = lines[0].replace('"n": 1', '"n": 999')
        path.write_text("\n".join(lines) + "\n")
        assert reg.verify_chain() is False

    def test_string_entry_type_accepted(self, tmp_path):
        reg = DecisionRegister(tmp_path / "reg.jsonl")
        e = reg.append("FREEZE_REQUEST", "A", {}, now=T0)
        assert e.entry_type == "FREEZE_REQUEST"

    def test_empty_register(self, tmp_path):
        reg = DecisionRegister(tmp_path / "reg.jsonl")
        assert reg.entries() == []
        assert reg.verify_chain() is True


class TestRegisterInternals:
    def test_path_property(self, tmp_path):
        p = tmp_path / "reg.jsonl"
        assert DecisionRegister(p).path == p

    def test_blank_lines_ignored(self, tmp_path):
        p = tmp_path / "reg.jsonl"
        reg = DecisionRegister(p)
        reg.append(EntryType.FREEZE_REQUEST, "A", {}, now=T0)
        p.write_text(p.read_text() + "\n\n")  # trailing blank lines
        assert len(reg.entries()) == 1

    def test_verify_chain_detects_dropped_entry(self, tmp_path):
        p = tmp_path / "reg.jsonl"
        reg = DecisionRegister(p)
        reg.append(EntryType.FREEZE_REQUEST, "A", {}, now=T0)
        reg.append(EntryType.FREEZE_REQUEST, "B", {}, now=T0)
        reg.append(EntryType.FREEZE_REQUEST, "C", {}, now=T0)
        # Drop the middle entry -> index/prev_hash chain breaks.
        lines = p.read_text().splitlines()
        p.write_text(lines[0] + "\n" + lines[2] + "\n")
        assert reg.verify_chain() is False
