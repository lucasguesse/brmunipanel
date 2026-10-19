"""Executable entry point for python -m brmunipanel."""

from __future__ import annotations

import sys

from brmunipanel.cli import main

if __name__ == "__main__":
    sys.exit(main())
