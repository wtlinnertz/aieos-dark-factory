# aieos-dark-factory

The AIEOS **autonomous pipeline conductor** — the third driver over the one engine
(sherpa and console are the other two; see ADR-0002). It walks the kit DAG
(`kit-manifest.yml`) lights-out, running each artifact's generate/validate
lifecycle through the harness, and **parks at every freeze gate for a human**. It
drives an artifact to `FREEZE_PENDING` and no further — it has no code path that
writes `FROZEN`.

## Boundary

This repo is a pure control plane. It imports **only** the `HarnessDriver` facade
(`src/driver.py`, a Protocol mirroring `aieos-agent-harness`'s 3-op facade) and
nothing from the harness internals. That boundary is the entire justification for
a separate repo; if the conductor reaches past the facade, the repo was a mistake.

## What it does (v0.1.0 — conductor spine)

- Loads `kit-manifest.yml` and builds the **freeze-DAG walk order** for a preset.
- Runs each artifact's lifecycle via the facade; on convergence, **brokers a
  freeze gate** to a human and parks; on exhaustion, **escalates**.
- Before every artifact, checks the andon **`.aieos/halt`** sentinel and the
  FR-019 initiative **lock** — either stands the run down.
- Records every gate/escalation/resume in an append-only, **hash-chained
  Decision Register** (`.aieos/decision-register.jsonl`) — lands roadmap FR-007.
- **Crash-resumable**: conductor state persists to `.aieos/conductor-state.json`.

## CLI

```
dark-factory plan --manifest <kit-manifest.yml> --preset Enhancement
```

`run` awaits the harness-driver integration seam (see `src/driver.py`).

## Staged (next slices)

Real harness wiring behind the facade; full andon (email summon, cost-anomaly +
liveness backstops); rewind-to-frozen recovery; the recursive dogfood launch demo.
