"""Core systems for PHANTOM.

The package is intentionally small and dependency-light:

* :mod:`core.brain` owns all communication with the local Ollama service.
* :mod:`core.personality` owns the system prompt and deterministic mood state.
* :mod:`core.memory` owns SQLite persistence for explicit user memories.

Importing this package does not contact Ollama or create a database.
"""

from .brain import (
    Brain,
    BrainConfig,
    BrainConfigError,
    BrainError,
    BrainStatus,
    BrainTimeoutError,
    ChatResult,
    EmptyResponseError,
    ExternalServiceError,
    InvalidMessageError,
    ModelNotFoundError,
    ModelResponseError,
    OllamaUnavailableError,
    StreamChunk,
    StreamInterruptedError,
)
from .memory import (
    AmbiguousMemoryError,
    InterpretationRecord,
    InvalidMemoryError,
    MemoryDatabaseError,
    MemoryHealth,
    MemoryNotFoundError,
    MemoryRecord,
    MemoryStore,
    PhantomMemoryError,
    SchemaVersionError,
    default_db_path,
)
from .personality import (
    MemoryNote,
    MoodEngine,
    MoodEvent,
    MoodState,
    build_system_prompt,
    format_mood,
)

__all__ = [
    "AmbiguousMemoryError",
    "Brain",
    "BrainConfig",
    "BrainConfigError",
    "BrainError",
    "BrainStatus",
    "BrainTimeoutError",
    "ChatResult",
    "EmptyResponseError",
    "ExternalServiceError",
    "InterpretationRecord",
    "InvalidMemoryError",
    "InvalidMessageError",
    "MemoryDatabaseError",
    "MemoryHealth",
    "MemoryNotFoundError",
    "MemoryNote",
    "MemoryRecord",
    "MemoryStore",
    "ModelNotFoundError",
    "ModelResponseError",
    "MoodEngine",
    "MoodEvent",
    "MoodState",
    "OllamaUnavailableError",
    "PhantomMemoryError",
    "SchemaVersionError",
    "StreamChunk",
    "StreamInterruptedError",
    "build_system_prompt",
    "default_db_path",
    "format_mood",
]
