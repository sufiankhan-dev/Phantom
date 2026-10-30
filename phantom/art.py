"""ASCII identity for PHANTOM.

The marks below are deliberately plain ASCII. They survive limited terminals,
legacy code pages, and the ``--plain`` output mode. Nothing in this module
performs work or describes a state; these are only shapes on the screen.
"""

from __future__ import annotations

PHANTOM_ART: tuple[str, ...] = (
    '       .-"""-.',
    "     .'       '.",
    "    /           \\",
    "   |   o     o   |",
    "   |      ^      |",
    "   |    .---.    |",
    "    \\  '-----'  /",
    "     '.       .'",
    "       '-...-'",
)

PHANTOM_FAREWELL_ART: tuple[str, ...] = (
    '       .-"""-.',
    "     .'       '.",
    "    /           \\",
    "   |   -     -   |",
    "   |      ^      |",
    "   |    .---.    |",
    "    \\  '-----'  /",
    "     '.       .'",
    "       '-...-'",
)

PHANTOM_SIGIL: tuple[str, ...] = (
    '  .-"""-.',
    " (  o o  )",
    "  '-...-'",
)

PHANTOM_FAREWELL_SIGIL: tuple[str, ...] = (
    '  .-"""-.',
    " (  - -  )",
    "  '-...-'",
)

WORDMARK = "P H A N T O M"
TAGLINE = "local intelligence / no cloud / no leash"
TAGLINE_SHORT = "local only / no cloud"
TAGLINE_TINY = "local only"

ART_WIDTH = max(len(line) for line in PHANTOM_ART)
SIGIL_WIDTH = max(len(line) for line in PHANTOM_SIGIL)

__all__ = [
    "ART_WIDTH",
    "PHANTOM_ART",
    "PHANTOM_FAREWELL_ART",
    "PHANTOM_FAREWELL_SIGIL",
    "PHANTOM_SIGIL",
    "SIGIL_WIDTH",
    "TAGLINE",
    "TAGLINE_SHORT",
    "TAGLINE_TINY",
    "WORDMARK",
]
