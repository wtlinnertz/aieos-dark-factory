"""CLI for the AIEOS dark factory conductor.

``plan``  -- print the freeze-DAG walk order for a preset (no driver needed).
``run``   -- drive an initiative through the conductor. Requires the harness
             driver to be wired (staged integration seam); until then it exits
             with a clear message rather than pretending.
"""

from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path

from src.manifest import build_walk_order, load_manifest


def _kits_for(manifest, preset_name: str) -> set[str]:
    p = manifest.preset(preset_name)
    return set(p.get("required_kits", []))


def cmd_plan(args: argparse.Namespace) -> int:
    manifest = load_manifest(Path(args.manifest))
    kits = _kits_for(manifest, args.preset)
    order = build_walk_order(manifest, kits, include_optional=args.include_optional)
    print(f"Preset: {args.preset}  ({len(order)} artifacts)")
    for i, node in enumerate(order, 1):
        print(f"  {i:>2}. {node}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Drive an initiative through the conductor against the real harness CLI."""
    import json

    from src.conductor import Conductor, ConductorStatus
    from src.subprocess_driver import SubprocessHarnessDriver

    manifest = load_manifest(Path(args.manifest))
    order = build_walk_order(manifest, _kits_for(manifest, args.preset))
    driver = SubprocessHarnessDriver(
        shlex.split(args.harness_cmd),
        Path(args.aieos_root),
        cwd=Path(args.harness_cwd) if args.harness_cwd else None,
    )
    state = Conductor(driver, Path(args.initiative), order).run()
    print(json.dumps({
        "status": state.status,
        "current": state.current,
        "completed": state.completed,
    }))
    return 1 if state.status == ConductorStatus.HALTED.value else 0


def cmd_resume(args: argparse.Namespace) -> int:
    """Clear a HALTED run (andon resume). Not a freeze; records to the register."""
    import json

    from src.andon import resume

    cleared = resume(Path(args.initiative), args.by, note=args.note or "")
    print(json.dumps({"resumed": cleared, "cleared_by": args.by}))
    return 0 if cleared else 1


def cmd_clear_fault(args: argparse.Namespace) -> int:
    """Record a human clear for a FAULTED run (andon), then drop the sentinel."""
    import json

    from src.andon import clear_fault

    cleared = clear_fault(Path(args.initiative), args.by, note=args.note or "")
    print(json.dumps({"cleared": True, "sentinel_removed": cleared, "cleared_by": args.by}))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="AIEOS dark factory -- autonomous pipeline conductor"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="Print the walk order for a preset")
    plan.add_argument("--manifest", required=True, help="Path to kit-manifest.yml")
    plan.add_argument("--preset", required=True, help="Preset name (e.g. Enhancement)")
    plan.add_argument("--include-optional", action="store_true")

    run = sub.add_parser("run", help="Drive an initiative via the harness CLI")
    run.add_argument("--initiative", required=True)
    run.add_argument("--manifest", required=True)
    run.add_argument("--preset", required=True)
    run.add_argument("--aieos-root", required=True, help="Kit files root for the harness")
    run.add_argument(
        "--harness-cmd", default="harness",
        help="Command to invoke the harness CLI (default: 'harness')",
    )
    run.add_argument(
        "--harness-cwd", default=None, help="Working dir for the harness command",
    )

    resume_p = sub.add_parser("resume", help="Clear a HALTED run (andon)")
    resume_p.add_argument("--initiative", required=True)
    resume_p.add_argument("--by", required=True, help="Human identity clearing the halt")
    resume_p.add_argument("--note", default=None)

    clear_p = sub.add_parser("clear-fault", help="Record a human clear for a FAULTED run (andon)")
    clear_p.add_argument("--initiative", required=True)
    clear_p.add_argument("--by", required=True, help="Human identity clearing the fault")
    clear_p.add_argument("--note", default=None)

    args = parser.parse_args(argv)
    handlers = {
        "plan": cmd_plan,
        "run": cmd_run,
        "resume": cmd_resume,
        "clear-fault": cmd_clear_fault,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())  # pragma: no cover
