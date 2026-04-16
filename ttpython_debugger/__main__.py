"""Lets `python -m ttpython_debugger ...` delegate to the CLI dispatcher."""

from .cli.__main__ import main

raise SystemExit(main())
