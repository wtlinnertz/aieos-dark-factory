"""Append-only, hash-chained Decision Register (lands roadmap FR-007).

Every freeze-gate brokered to a human, every escalation, and every andon
resume/clear is recorded here as an immutable, ordered entry. Each entry is
hash-chained through the previous entry's hash, so any tampering or dropped entry
breaks ``verify_chain``. Persisted as JSONL under the initiative so it survives a
conductor crash and is auditable after the fact.

A resume/clear is a *sibling entry type* here -- it is never a freeze and never
routes through apply_freeze_decision (ADR-0004).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

GENESIS = "GENESIS"


class EntryType(str, Enum):
    FREEZE_REQUEST = "FREEZE_REQUEST"
    ESCALATION = "ESCALATION"
    RESUME = "RESUME"
    CLEAR_FAULT = "CLEAR_FAULT"
    HALT = "HALT"


@dataclass
class RegisterEntry:
    index: int
    prev_hash: str
    timestamp: str
    entry_type: str
    artifact_id: str
    payload: dict
    entry_hash: str


def _canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _hash(
    prev_hash: str,
    index: int,
    timestamp: str,
    entry_type: str,
    artifact_id: str,
    payload: dict,
) -> str:
    material = "|".join(
        [prev_hash, str(index), timestamp, entry_type, artifact_id, _canonical(payload)]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class DecisionRegister:
    """JSONL append-only register at ``.aieos/decision-register.jsonl``."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def entries(self) -> list[RegisterEntry]:
        if not self._path.exists():
            return []
        out: list[RegisterEntry] = []
        for line in self._path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            out.append(RegisterEntry(**json.loads(line)))
        return out

    def append(
        self,
        entry_type: EntryType | str,
        artifact_id: str,
        payload: dict,
        *,
        now: Optional[datetime] = None,
    ) -> RegisterEntry:
        etype = entry_type.value if isinstance(entry_type, EntryType) else str(entry_type)
        ts = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
        existing = self.entries()
        index = len(existing)
        prev_hash = existing[-1].entry_hash if existing else GENESIS
        entry_hash = _hash(prev_hash, index, ts, etype, artifact_id, payload)
        entry = RegisterEntry(
            index=index,
            prev_hash=prev_hash,
            timestamp=ts,
            entry_type=etype,
            artifact_id=artifact_id,
            payload=payload,
            entry_hash=entry_hash,
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a") as f:
            f.write(json.dumps(asdict(entry)) + "\n")
        return entry

    def verify_chain(self) -> bool:
        """True iff every entry's hash and prev-link are internally consistent."""
        prev = GENESIS
        for i, e in enumerate(self.entries()):
            if e.index != i or e.prev_hash != prev:
                return False
            expected = _hash(
                e.prev_hash, e.index, e.timestamp, e.entry_type, e.artifact_id, e.payload
            )
            if expected != e.entry_hash:
                return False
            prev = e.entry_hash
        return True
