#!/usr/bin/python3
"""Convenience launcher so the CLI can be run as `python ratewatch.py ...`.

`python -m src.main ...` from the project root does exactly the same thing.

The shebang is deliberately not the usual `/usr/bin/env python3`: the Windows
`py` launcher reads shebangs, and the `env` form makes it search PATH, where it
finds the Microsoft Store stub instead of a real interpreter. This form maps to
the newest installed Python 3 on Windows and stays valid on Linux and macOS.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.main import main  # noqa: E402  (import must follow the path setup)

if __name__ == "__main__":
    sys.exit(main())
