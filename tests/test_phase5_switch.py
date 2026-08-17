"""Phase 5 — three-way switch proof (the release gate), as a guarded integration test.

Exercises the full loop against the REAL harness CLI + the offline converging mock
provider: dark factory runs lights-out -> parks at a freeze gate -> a human
freezes (the console's role, via the harness freeze authority) -> the conductor
resumes on the advanced frozen count -> walks to COMPLETED. Verifies the single
canonical Document Control representation and the hash-chained Decision Register.

Guarded: skips unless the harness repo is locatable (env AIEOS_HARNESS_PATH, or a
sibling ../aieos-agent-harness). CI wires this by checking out the harness sibling
(mirrors the sherpa CI checking out governance-foundation).
"""

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from src.conductor import Conductor, ConductorStatus
from src.decision_register import DecisionRegister
from src.subprocess_driver import SubprocessHarnessDriver


def _harness_path() -> Path | None:
    env = os.environ.get("AIEOS_HARNESS_PATH")
    if env and (Path(env) / "src" / "cli.py").exists():
        return Path(env)
    sibling = Path(__file__).resolve().parents[2] / "aieos-agent-harness"
    if (sibling / "src" / "cli.py").exists():
        return sibling
    return None


HARNESS = _harness_path()
pytestmark = pytest.mark.skipif(
    HARNESS is None, reason="harness repo not found (set AIEOS_HARNESS_PATH)"
)


def _setup(work: Path):
    init = work / "aicr-demo"
    (init / "docs" / "sdlc").mkdir(parents=True)
    eng = init / "docs" / "engagement"
    eng.mkdir(parents=True)
    (eng / "er.md").write_text(
        "# ER\n\n## 1b state block\n\n| Field | Value |\n|--|--|\n"
        "| Current Layer | Layer 4 |\n| Current Artifact | EEK:PRD |\n"
        "| Current Step | Generation |\n| Frozen Count | 0 |\n"
        "| Next Action | run |\n| Blocking On | None |\n| Last Updated | 2026-07-12T00:00:00Z |\n"
    )
    aieos_root = work / "aieos"
    kit = aieos_root / "aieos-eek"
    for sub in ("specs", "artifacts", "prompts"):
        (kit / "docs" / sub).mkdir(parents=True)
    for t in ("prd", "sad"):
        (kit / "docs" / "specs" / f"{t}-spec.md").write_text(f"# {t} spec")
        (kit / "docs" / "artifacts" / f"{t}-template.md").write_text("template")
        (kit / "docs" / "prompts" / f"{t}-prompt.md").write_text("prompt")
    hy = work / "harness.yaml"
    hy.write_text("providers:\n  mock:\n    enabled: true\n    model: converging-mock-v1\n")
    return init, aieos_root, hy


def test_three_way_switch(tmp_path):
    init, aieos_root, hy = _setup(tmp_path)
    harness_cmd = [sys.executable, "-m", "src.cli", "--config", str(hy)]
    driver = SubprocessHarnessDriver(harness_cmd, aieos_root, cwd=HARNESS)
    conductor = Conductor(driver, init, ["EEK:PRD", "EEK:SAD"])

    def human_freeze(artifact_file: Path):
        text = artifact_file.read_text()
        aid = re.search(r"\|\s*Artifact ID\s*\|\s*(.*?)\s*\|", text).group(1).strip()
        dec = tmp_path / "decision.json"
        dec.write_text(json.dumps({
            "artifact_id": aid, "outcome": "APPROVE",
            "content_hash": hashlib.sha256(text.encode()).hexdigest(),
            "decided_by": "Todd (console)",
        }))
        r = subprocess.run(
            harness_cmd + ["freeze", "--initiative", str(init), "--decision", str(dec)],
            capture_output=True, text=True, cwd=str(HARNESS), check=False,
        )
        assert r.returncode == 0, r.stderr

    # 1. lights-out -> park at PRD
    st = conductor.run()
    assert st.status == ConductorStatus.PARKED_AT_GATE.value
    assert st.current == "EEK:PRD"
    assert (init / "docs" / "sdlc" / "prd.md").exists()

    # 2. human freezes PRD (console role); 3. conductor advances to SAD
    human_freeze(init / "docs" / "sdlc" / "prd.md")
    st = conductor.run()
    assert st.status == ConductorStatus.PARKED_AT_GATE.value
    assert st.current == "EEK:SAD"
    assert "EEK:PRD" in st.completed

    # 4. freeze SAD; 5. complete
    human_freeze(init / "docs" / "sdlc" / "sad.md")
    st = conductor.run()
    assert st.status == ConductorStatus.COMPLETED.value
    assert st.completed == ["EEK:PRD", "EEK:SAD"]

    # 6. one representation + audit trail
    rs = subprocess.run(
        harness_cmd + ["read-state", "--initiative", str(init)],
        capture_output=True, text=True, cwd=str(HARNESS), check=False,
    )
    assert json.loads(rs.stdout)["frozen_count"] == 2
    for md in (init / "docs" / "sdlc").glob("*.md"):
        txt = md.read_text()
        assert re.search(r"\|\s*Status\s*\|\s*FROZEN\s*\|", txt), md.name
    reg = DecisionRegister(init / ".aieos" / "decision-register.jsonl")
    assert reg.verify_chain()


def test_escalation_surface(tmp_path):
    """Phase 5 escalation bullet: convergence exhaustion -> conductor ESCALATED,
    recorded in the Decision Register (live, against the real harness)."""
    init, aieos_root, _hy = _setup(tmp_path)
    hy = tmp_path / "harness-fail.yaml"
    hy.write_text("providers:\n  mock_fail:\n    enabled: true\n    model: failing-mock-v1\n")
    harness_cmd = [sys.executable, "-m", "src.cli", "--config", str(hy)]
    driver = SubprocessHarnessDriver(harness_cmd, aieos_root, cwd=HARNESS)
    conductor = Conductor(driver, init, ["EEK:PRD", "EEK:SAD"])

    st = conductor.run()
    assert st.status == ConductorStatus.ESCALATED.value
    assert st.current == "EEK:PRD"
    # no artifact persisted; escalation recorded in the register
    assert not (init / "docs" / "sdlc" / "prd.md").exists()
    reg = DecisionRegister(init / ".aieos" / "decision-register.jsonl")
    assert reg.verify_chain()
    assert reg.entries()[-1].entry_type == "ESCALATION"
