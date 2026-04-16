"""Deadline violation detection — the first implemented feature.

Inputs
------
  - A deadlines spec file (YAML) declaring the programmer's contracts.
  - TTPython runtime JSONL logs from a real cluster run.

Outputs
-------
  - A list of Violation objects and a plain-text report.

See ../../DEADLINE_VIOLATIONS.md at the repo root for the full story.
"""

from .spec import Deadlines
from .detect import Violation, check_end_to_end, check_per_sq
from .report import end_to_end_summary, per_sq_summary

__all__ = [
    "Deadlines", "Violation",
    "check_end_to_end", "check_per_sq",
    "end_to_end_summary", "per_sq_summary",
]
