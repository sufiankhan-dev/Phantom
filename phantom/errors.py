"""Typed command failures and their process exit codes."""

from __future__ import annotations

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_DEPENDENCY = 3
EXIT_DATABASE = 4
EXIT_INSPECTION = 5
EXIT_INTERRUPTED = 130


class CliError(Exception):
    """A failure that can be explained to the user without a traceback."""

    exit_code = 1
    title = "Error"

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        self.message = message
        self.hint = hint
        super().__init__(message)

    def __str__(self) -> str:
        return self.message


class UsageError(CliError):
    """The user supplied invalid input or an impossible combination."""

    exit_code = EXIT_USAGE
    title = "Invalid request"


class DependencyError(CliError):
    """A required local dependency (usually Ollama) is missing."""

    exit_code = EXIT_DEPENDENCY
    title = "Local model unavailable"


class DatabaseError(CliError):
    """The memory archive could not be read or written."""

    exit_code = EXIT_DATABASE
    title = "Memory archive error"


class InspectionError(CliError):
    """Inspection could not be completed."""

    exit_code = EXIT_INSPECTION
    title = "Inspection unavailable"


class InterruptedError(CliError):
    """The user interrupted an operation."""

    exit_code = EXIT_INTERRUPTED
    title = "Interrupted"
