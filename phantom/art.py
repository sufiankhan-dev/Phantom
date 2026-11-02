"""Identity text for PHANTOM.

The UI shows no faces or ASCII figures, so this module holds only plain text:
the wordmark and its taglines. Every value survives limited terminals, legacy
code pages, and the ``--plain`` output mode. Nothing here performs work or
describes a state; these are only words on the screen.
"""

from __future__ import annotations

WORDMARK = "P H A N T O M"
WORDMARK_COMPACT = "PHANTOM"
TAGLINE = "local intelligence / no cloud / no leash"
TAGLINE_SHORT = "local only / no cloud"
TAGLINE_TINY = "local only"

__all__ = [
    "TAGLINE",
    "TAGLINE_SHORT",
    "TAGLINE_TINY",
    "WORDMARK",
    "WORDMARK_COMPACT",
]
