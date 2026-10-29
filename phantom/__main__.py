"""Support ``python -m phantom`` as an alias for ``python -m phantom.main``."""

from __future__ import annotations

import sys

from phantom.main import main

if __name__ == "__main__":
    sys.exit(main())
