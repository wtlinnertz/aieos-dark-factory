"""Tests for manifest loading + freeze-DAG walk order."""

from pathlib import Path

import pytest

from src.manifest import build_walk_order, load_manifest

MANIFEST = Path(__file__).parent / "fixtures" / "kit-manifest.yml"


@pytest.fixture(scope="module")
def manifest():
    return load_manifest(MANIFEST)


class TestLoad:
    def test_loads_kits(self, manifest):
        assert manifest.manifest_version == "1.0"
        assert "EEK" in manifest.kits
        assert manifest.kits["EEK"].layer == 4

    def test_edges_and_presets(self, manifest):
        assert any(e.type == "freeze" for e in manifest.edges)
        assert "Enhancement" in manifest.presets

    def test_unknown_preset_raises(self, manifest):
        with pytest.raises(KeyError):
            manifest.preset("Nope")


class TestWalkOrder:
    def test_enhancement_order_respects_freeze_edges(self, manifest):
        order = build_walk_order(manifest, {"EEK", "REK"})
        pos = {n: i for i, n in enumerate(order)}
        # within-EEK
        assert pos["EEK:KER"] < pos["EEK:PRD"] < pos["EEK:ACF"]
        assert pos["EEK:PRD"] < pos["EEK:SAD"]
        assert pos["EEK:SAD"] < pos["EEK:TDD"]
        assert pos["EEK:WDD"] < pos["EEK:ORD"]
        # cross-kit: ORD (EEK) gates RER (REK)
        assert pos["EEK:ORD"] < pos["REK:RER"]
        assert pos["REK:RER"] < pos["REK:RR"]

    def test_optional_artifacts_skipped_by_default(self, manifest):
        order = build_walk_order(manifest, {"EEK"})
        assert "EEK:DKR" not in order  # DKR is optional

    def test_optional_included_when_requested(self, manifest):
        order = build_walk_order(manifest, {"EEK"}, include_optional=True)
        assert "EEK:DKR" in order

    def test_unknown_kit_raises(self, manifest):
        with pytest.raises(KeyError):
            build_walk_order(manifest, {"ZZZ"})

    def test_all_selected_nodes_present(self, manifest):
        order = build_walk_order(manifest, {"REK"})
        assert set(order) == {
            "REK:RER", "REK:RCF", "REK:RSA", "REK:RP", "REK:RR"
        }


class TestWalkOrderInternals:
    def test_preset_happy_path(self, manifest):
        p = manifest.preset("Enhancement")
        assert p["entry_point"] == "EEK:KER"

    def test_cycle_detection(self):
        from src.manifest import Artifact, Edge, Kit, Manifest

        kit = Kit(
            abbr="A", layer=1, category="pipeline", status="built", optional=False,
            artifacts=[Artifact(id="X", full_name="X"), Artifact(id="Y", full_name="Y")],
            artifact_flow=["X", "Y"],
        )
        m = Manifest(
            manifest_version="1.0",
            kits={"A": kit},
            edges=[Edge("A:X", "A:Y", "freeze"), Edge("A:Y", "A:X", "freeze")],
            presets={},
        )
        with pytest.raises(ValueError, match="cycle"):
            build_walk_order(m, {"A"})
