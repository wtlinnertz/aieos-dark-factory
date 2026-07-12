"""CLI for the AIEOS dark factory conductor.

``plan``  -- print the freeze-DAG walk order for a preset (no driver needed).
``run``   -- drive an initiative through the conductor. Requires the harness
             driver to be wired (staged integration seam); until then it exits
             with a clear message rather than pretending.
"""

from __future__ import annotations

import argparse
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
    print(
        "run: the harness driver is not yet wired into the dark factory "
        "(staged integration seam -- see src/driver.py). Use `plan` to inspect "
        "the walk order.",
        file=sys.stderr,
    )
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="AIEOS dark factory -- autonomous pipeline conductor"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="Print the walk order for a preset")
    plan.add_argument("--manifest", required=True, help="Path to kit-manifest.yml")
    plan.add_argument("--preset", required=True, help="Preset name (e.g. Enhancement)")
    plan.add_argument("--include-optional", action="store_true")

    run = sub.add_parser("run", help="Drive an initiative (needs harness driver)")
    run.add_argument("--initiative", required=True)
    run.add_argument("--manifest", required=True)
    run.add_argument("--preset", required=True)

    args = parser.parse_args(argv)
    handlers = {"plan": cmd_plan, "run": cmd_run}
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())  # pragma: no cover
