"""Text shared by the argparse epilog and the Rich help page.

Keeping one source for both means ``phantom --help`` and
``phantom COMMAND --help`` cannot drift apart.
"""

from __future__ import annotations

COMMANDS: tuple[tuple[str, str], ...] = (
    ("(no command)", "Awaken the entity: checks, archive, introduction."),
    ("awaken", "Check dependencies, open the archive, and introduce PHANTOM."),
    ("chat", "Start an interactive, streamed conversation."),
    ("inspect PATH", "Inspect a file or directory in read-only mode."),
    ("remember TEXT", "Archive one explicit memory."),
    ("memories", "List archived memories with IDs and timestamps."),
    ("forget ID", "Delete one memory after confirmation."),
    ("status", "Report model connectivity, configuration, and archive health."),
    ("exorcise", "Close the session without deleting anything."),
)

EXAMPLES: tuple[str, ...] = (
    "phantom",
    "phantom chat",
    "phantom inspect .",
    'phantom remember "I prefer pytest and short answers."',
    "phantom forget 1",
    "phantom status",
    "phantom exorcise",
    "phantom --help",
)

MODEL: tuple[tuple[str, str], ...] = (
    ("default model", "qwen3:8b, used through the Ollama Python package"),
    ("override", "--model NAME or PHANTOM_MODEL"),
    ("missing model", "PHANTOM prints `ollama pull qwen3:8b` and stops"),
    (
        "never automatic",
        "no model download, no background service, no paid API",
    ),
)

ENVIRONMENT: tuple[tuple[str, str], ...] = (
    ("PHANTOM_MODEL", "model name (default: qwen3:8b)"),
    ("PHANTOM_OLLAMA_HOST", "Ollama endpoint (default: http://127.0.0.1:11434)"),
    ("OLLAMA_HOST", "used when PHANTOM_OLLAMA_HOST is unset"),
    ("PHANTOM_DB", "database path (default: ~/.phantom/phantom.db)"),
    ("PHANTOM_HOME", "directory holding phantom.db"),
    ("PHANTOM_TIMEOUT", "model read timeout in seconds"),
    ("PHANTOM_ALLOW_REMOTE_OLLAMA=1", "permit a non-loopback Ollama host"),
    ("NO_COLOR", "disable colour and animation"),
    ("TERM=dumb", "disable colour and animation"),
)

DISPLAY: tuple[tuple[str, str], ...] = (
    ("--plain", "ASCII only, no colour, no animation"),
    ("--no-animation", "keep styling, skip the short reveals"),
    ("redirected stdout", "ASCII borders, no animation, real results"),
)

EXIT_CODES: tuple[tuple[str, str], ...] = (
    ("0", "success"),
    ("2", "invalid input"),
    ("3", "local model unavailable"),
    ("4", "database error"),
    ("5", "inspection refused or unreadable"),
    ("130", "interrupted"),
)

DEVELOPMENT = (
    "python -m phantom.main ...    development fallback when the console "
    "script is not installed"
)


def build_epilog() -> str:
    """Render the classic plain text epilog used by argparse."""

    lines = [
        "examples:",
        *(f"  $ {command}" for command in EXAMPLES),
        "",
        "Running `phantom` with no command awakens the entity: it checks local",
        "dependencies, initializes the archive, and introduces PHANTOM.",
        "",
        "model:",
        *(f"  {key:<14} {value}" for key, value in MODEL),
        "",
        "environment:",
        *(f"  {key:<30} {value}" for key, value in ENVIRONMENT),
        "",
        "display:",
        *(f"  {key:<30} {value}" for key, value in DISPLAY),
        "",
        "development:",
        f"  {DEVELOPMENT}",
        "",
        "exit codes:",
        *(
            f"  {code:<3} {meaning}"
            for code, meaning in EXIT_CODES
        ),
    ]
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "COMMANDS",
    "DEVELOPMENT",
    "DISPLAY",
    "ENVIRONMENT",
    "EXAMPLES",
    "EXIT_CODES",
    "MODEL",
    "build_epilog",
]
