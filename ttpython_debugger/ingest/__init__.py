"""Readers for TTPython runtime outputs.

A real TTPython cluster run produces JSONL files on each device. Every
debugger feature consumes the same raw data; keeping the parsers here
in one place means new features just import them.

Current readers:
  - runtime_log.read_runtime_log(path) -> list[EndToEndRecord]
  - sq_timing.read_sq_timing(path)    -> list[SqRecord]
"""

from .runtime_log import EndToEndRecord, read_runtime_log
from .sq_timing import SqRecord, read_sq_timing

__all__ = [
    "EndToEndRecord", "read_runtime_log",
    "SqRecord", "read_sq_timing",
]
