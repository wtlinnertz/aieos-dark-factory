"""Load kit-manifest.yml and produce the conductor's freeze-DAG walk order.

The manifest (aieos-governance-foundation/kit-manifest.yml) is the machine-
readable DAG of every kit, artifact, and dependency edge. The dark factory walks
it; it does not own it. Only ``freeze`` edges gate ordering here -- ``trigger``
and ``escalation`` edges are separate concerns (cross-cutting activation and
reverse re-entry) handled in later slices.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Artifact:
    id: str
    full_name: str
    human_authored: bool = False
    optional: bool = False


@dataclass
class Kit:
    abbr: str
    layer: int
    category: str
    status: str
    optional: bool
    artifacts: list[Artifact] = field(default_factory=list)
    artifact_flow: list[str] = field(default_factory=list)


@dataclass
class Edge:
    frm: str  # "KIT:ARTIFACT"
    to: str
    type: str  # freeze | trigger | escalation


@dataclass
class Manifest:
    manifest_version: str
    kits: dict[str, Kit]
    edges: list[Edge]
    presets: dict[str, dict]

    def preset(self, name: str) -> dict:
        if name not in self.presets:
            raise KeyError(
                f"Unknown preset {name!r}; have {sorted(self.presets)}"
            )
        return self.presets[name]


def load_manifest(path: Path) -> Manifest:
    data = yaml.safe_load(Path(path).read_text())

    kits: dict[str, Kit] = {}
    for abbr, k in data.get("kits", {}).items():
        artifacts = [
            Artifact(
                id=a["id"],
                full_name=a.get("full_name", ""),
                human_authored=a.get("human_authored", False),
                optional=a.get("optional", False),
            )
            for a in k.get("artifacts", [])
        ]
        kits[abbr] = Kit(
            abbr=abbr,
            layer=k.get("layer", 0),
            category=k.get("category", ""),
            status=k.get("status", ""),
            optional=k.get("optional", False),
            artifacts=artifacts,
            artifact_flow=list(k.get("artifact_flow", [])),
        )

    edges = [
        Edge(frm=e["from"], to=e["to"], type=e["type"])
        for e in data.get("dependency_edges", [])
    ]

    presets = {p["name"]: p for p in data.get("presets", [])}

    return Manifest(
        manifest_version=str(data.get("manifest_version", "")),
        kits=kits,
        edges=edges,
        presets=presets,
    )


def _node(kit: str, artifact: str) -> str:
    return f"{kit}:{artifact}"


def build_walk_order(
    manifest: Manifest,
    kits: set[str],
    *,
    include_optional: bool = False,
) -> list[str]:
    """Topologically ordered ``KIT:ARTIFACT`` nodes for the selected kits.

    Ordering is the transitive freeze-edge DAG restricted to the selected kits.
    Optional artifacts are skipped unless ``include_optional``. Ties break by
    (layer, artifact_flow index) so the order is deterministic and matches the
    intended pipeline sequence.
    """
    # Enumerate selected nodes + a stable sort key per node.
    order_key: dict[str, tuple[int, int]] = {}
    nodes: set[str] = set()
    for abbr in kits:
        kit = manifest.kits.get(abbr)
        if kit is None:
            raise KeyError(f"Unknown kit {abbr!r}")
        flow_index = {aid: i for i, aid in enumerate(kit.artifact_flow)}
        for art in kit.artifacts:
            if art.optional and not include_optional:
                continue
            node = _node(abbr, art.id)
            nodes.add(node)
            order_key[node] = (kit.layer, flow_index.get(art.id, 999))

    # Freeze edges among selected nodes only.
    incoming: dict[str, set[str]] = {n: set() for n in nodes}
    outgoing: dict[str, set[str]] = {n: set() for n in nodes}
    for e in manifest.edges:
        if e.type != "freeze":
            continue
        if e.frm in nodes and e.to in nodes:
            incoming[e.to].add(e.frm)
            outgoing[e.frm].add(e.to)

    # Kahn's algorithm with deterministic tiebreak.
    ready = sorted((n for n in nodes if not incoming[n]), key=lambda n: order_key[n])
    result: list[str] = []
    incoming_count = {n: len(incoming[n]) for n in nodes}

    while ready:
        n = ready.pop(0)
        result.append(n)
        newly_ready = []
        for m in outgoing[n]:
            incoming_count[m] -= 1
            if incoming_count[m] == 0:
                newly_ready.append(m)
        if newly_ready:
            ready.extend(newly_ready)
            ready.sort(key=lambda n: order_key[n])

    if len(result) != len(nodes):
        cyclic = sorted(nodes - set(result))
        raise ValueError(f"Freeze-edge cycle among selected nodes: {cyclic}")

    return result
