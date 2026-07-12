# CLAUDE.md — aieos-dark-factory

## What this repo is
The AIEOS autonomous pipeline conductor ("dark factory"), the third driver over
the shared engine (ADR-0002). Pure control plane: it sequences; the harness
governs. It imports **only** the `HarnessDriver` facade — never harness internals.

## Hard rules
- **Never write `FROZEN`.** The conductor drives artifacts to `FREEZE_PENDING`
  and parks at a human freeze gate. Only the harness `apply_freeze_decision`
  writes `FROZEN`. The conductor never calls it.
- **Import only the facade** (`src/driver.py`). Do not import from
  `aieos-agent-harness` internals (convergence, state, invariants).
- **Andon before every artifact:** check `.aieos/halt` and the FR-019 lock; stand
  down (HALTED) if either says so.
- Resume/clear is **not** a freeze — it routes through the Decision Register.

## Structure
- `src/manifest.py`  — load kit-manifest.yml; build freeze-DAG walk order
- `src/driver.py`    — HarnessDriver facade Protocol (the boundary)
- `src/decision_register.py` — append-only hash-chained register (FR-007)
- `src/conductor.py` — walk / gate-park / escalate / halt / crash-resume
- `src/cli.py`       — `plan` (walk order), `run` (awaits driver wiring)

## Tests
`pytest` — pure Python, uses a fake driver. Keep new modules at 100% line coverage.
