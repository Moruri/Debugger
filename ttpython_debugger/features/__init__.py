"""One sub-package per debugger feature.

Each sub-package either implements a full feature or is a named
placeholder for work planned in ROADMAP.md.

Implemented today:
  - deadlines           Deadline violation detection (temporal assertions).

Planned (currently empty stubs):
  - adaptation          Explain why the runtime remapped an SQ.
  - rootcause           Explain why a timing violation happened.
  - counterfactual      Evaluate alternative placements against real traces.
  - energy              Per-device energy / power hotspots.
  - global_view         Unified cross-device execution view.
"""
