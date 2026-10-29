"""Entry point for ``python -m phantom.main``."""

from __future__ import annotations

import sys
from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return its exit code."""

    from phantom.cli import main as cli_main

    return cli_main(argv)


if __name__ == "__main__":
    sys.exit(main())
