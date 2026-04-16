"""`python -m ttpython_debugger <subcommand> ...`.

Each feature owns one subcommand. Today only `deadlines` is wired in;
placeholders below show where future features will slot in.
"""

from __future__ import annotations

import argparse
import sys

from . import deadlines as deadlines_cmd


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m ttpython_debugger",
        description="Debugger for distributed time-sensitive TTPython "
                    "applications. Consumes real cluster JSONL traces.",
    )
    subs = ap.add_subparsers(dest="command", required=True)

    # Implemented.
    deadlines_cmd.register(subs)

    # Placeholders so `--help` advertises the full debugger surface.
    # Each prints a "not implemented yet" message when invoked.
    for name, blurb in [
        ("adaptation",     "Explain why the runtime remapped an SQ."),
        ("rootcause",      "Explain why a timing violation happened."),
        ("counterfactual", "Evaluate alternative placements."),
        ("energy",         "Per-device energy / power hotspots."),
        ("global-view",    "Unified cross-device execution view."),
    ]:
        p = subs.add_parser(name, help=f"(planned) {blurb}")
        p.set_defaults(func=_not_implemented(name))

    args = ap.parse_args(argv)
    return args.func(args)


def _not_implemented(name: str):
    def run(_args) -> int:
        print(f"`{name}` is planned but not implemented yet. "
              f"See ROADMAP.md.", file=sys.stderr)
        return 2
    return run


if __name__ == "__main__":
    raise SystemExit(main())
