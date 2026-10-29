"""Local-only inference through Ollama.

This module is the single boundary between PHANTOM and a language model. It
never downloads a model, never starts a service, and never contacts anything
except the configured Ollama host. Non-loopback hosts are rejected unless the
caller explicitly opts in.
"""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from typing import Any, Iterator, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit

DEFAULT_MODEL = "qwen3:8b"
DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_TIMEOUT = 300.0
DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_NUM_CTX = 4096
DEFAULT_NUM_PREDICT = 512
DEFAULT_TEMPERATURE = 0.7
OLLAMA_DEFAULT_PORT = 11434


class BrainError(Exception):
    """Base class for model failures with an actionable recovery hint."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        self.message = message
        self.hint = hint
        super().__init__(message)

    def __str__(self) -> str:
        if self.hint:
            return f"{self.message} {self.hint}"
        return self.message


class BrainConfigError(BrainError):
    """The requested brain configuration is invalid."""


class ExternalServiceError(BrainError):
    """A non-local Ollama host was requested without explicit consent."""


class OllamaUnavailableError(BrainError):
    """The local Ollama service cannot be reached."""


class ModelNotFoundError(BrainError):
    """The requested model is not installed locally."""

    def __init__(
        self,
        model: str,
        available: Sequence[str] = (),
        *,
        hint: str | None = None,
    ) -> None:
        self.model = model
        self.available = tuple(available)
        if hint is None:
            hint = (
                f"Install it with `ollama pull {model}`. "
                "PHANTOM never downloads models automatically."
            )
        super().__init__(f"Model {model!r} is not installed in Ollama.", hint=hint)


class ModelResponseError(BrainError):
    """Ollama accepted the request but returned an unusable response."""


class BrainTimeoutError(BrainError):
    """The local model did not answer within the configured timeout."""


class EmptyResponseError(BrainError):
    """The model stream completed without producing any text."""


class StreamInterruptedError(BrainError):
    """A stream failed after it may already have emitted text."""

    def __init__(
        self,
        message: str,
        *,
        partial_text: str = "",
        hint: str | None = None,
    ) -> None:
        self.partial_text = partial_text
        super().__init__(message, hint=hint)


class InvalidMessageError(BrainError):
    """The caller supplied an invalid chat message."""


@dataclass(frozen=True, slots=True)
class BrainConfig:
    """Configuration for the local model boundary."""

    model: str = DEFAULT_MODEL
    host: str = DEFAULT_HOST
    timeout: float = DEFAULT_TIMEOUT
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT
    num_ctx: int = DEFAULT_NUM_CTX
    num_predict: int = DEFAULT_NUM_PREDICT
    temperature: float = DEFAULT_TEMPERATURE
    think: bool | None = None
    allow_remote: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.model, str):
            raise BrainConfigError("The model name must be text.")
        model = self.model.strip()
        if not model:
            raise BrainConfigError("The model name cannot be empty.")
        object.__setattr__(self, "model", model)

        host = normalize_host(self.host)
        if not self.allow_remote and not is_loopback_host(host):
            raise ExternalServiceError(
                f"Refusing to contact non-local Ollama host {host!r}.",
                hint=(
                    "PHANTOM only talks to a local Ollama by default. "
                    "If you accept that prompts leave this machine, set "
                    "allow_remote=True or PHANTOM_ALLOW_REMOTE_OLLAMA=1."
                ),
            )
        object.__setattr__(self, "host", host)

        for name, value in (
            ("timeout", self.timeout),
            ("connect_timeout", self.connect_timeout),
        ):
            if not isinstance(value, (int, float)) or float(value) <= 0:
                raise BrainConfigError(f"{name} must be greater than zero.")
        for name, value in (("num_ctx", self.num_ctx), ("num_predict", self.num_predict)):
            if not isinstance(value, int) or value <= 0:
                raise BrainConfigError(f"{name} must be a positive integer.")
        if not 0.0 <= float(self.temperature) <= 2.0:
            raise BrainConfigError("temperature must be between 0.0 and 2.0.")
        if self.think not in (None, True, False):
            raise BrainConfigError("think must be True, False, or None.")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "BrainConfig":
        """Build a config from environment variables.

        ``PHANTOM_MODEL`` selects the model, ``OLLAMA_HOST`` (or
        ``PHANTOM_OLLAMA_HOST``) selects the local endpoint, and
        ``PHANTOM_ALLOW_REMOTE_OLLAMA`` must be explicitly truthy to allow a
        non-loopback host.
        """

        values = os.environ if env is None else env
        model = (values.get("PHANTOM_MODEL") or DEFAULT_MODEL).strip()
        host = (
            values.get("PHANTOM_OLLAMA_HOST")
            or values.get("OLLAMA_HOST")
            or DEFAULT_HOST
        ).strip()
        allow_remote = _env_bool(values.get("PHANTOM_ALLOW_REMOTE_OLLAMA"))
        timeout = _env_float(values.get("PHANTOM_TIMEOUT"), DEFAULT_TIMEOUT, "PHANTOM_TIMEOUT")
        num_ctx = _env_int(values.get("PHANTOM_NUM_CTX"), DEFAULT_NUM_CTX, "PHANTOM_NUM_CTX")
        num_predict = _env_int(
            values.get("PHANTOM_NUM_PREDICT"),
            DEFAULT_NUM_PREDICT,
            "PHANTOM_NUM_PREDICT",
        )
        return cls(
            model=model,
            host=host,
            timeout=timeout,
            num_ctx=num_ctx,
            num_predict=num_predict,
            allow_remote=allow_remote,
        )


@dataclass(frozen=True, slots=True)
class BrainStatus:
    """Result of a non-fatal Ollama health check."""

    host: str
    model: str
    reachable: bool
    model_available: bool
    models: tuple[str, ...] = ()
    error: str | None = None


@dataclass(frozen=True, slots=True)
class StreamChunk:
    """One incremental piece of a model response."""

    content: str = ""
    thinking: str | None = None
    done: bool = False
    eval_count: int | None = None
    eval_duration_ns: int | None = None

    @property
    def tokens_per_second(self) -> float | None:
        if not self.eval_count or not self.eval_duration_ns:
            return None
        return self.eval_count / (self.eval_duration_ns / 1_000_000_000)


@dataclass(frozen=True, slots=True)
class ChatResult:
    """A fully collected model response."""

    text: str
    model: str
    thinking: str | None = None
    eval_count: int | None = None
    eval_duration_ns: int | None = None

    @property
    def tokens_per_second(self) -> float | None:
        if not self.eval_count or not self.eval_duration_ns:
            return None
        return self.eval_count / (self.eval_duration_ns / 1_000_000_000)


def normalize_host(host: str) -> str:
    """Normalize an Ollama host into a scheme + host + port URL."""

    if not isinstance(host, str):
        raise BrainConfigError("The Ollama host must be text.")
    raw = (host or "").strip()
    if not raw:
        raw = DEFAULT_HOST
    if raw.startswith(":"):
        raw = f"127.0.0.1{raw}"
    if "://" not in raw:
        raw = f"http://{raw}"

    parts = urlsplit(raw)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise BrainConfigError(
            f"Invalid Ollama host {host!r}.",
            hint="Use a URL such as http://127.0.0.1:11434.",
        )
    if parts.username or parts.password:
        raise BrainConfigError("Ollama host URLs must not contain credentials.")
    if parts.path not in {"", "/"} or parts.query or parts.fragment:
        raise BrainConfigError("Ollama host URLs must not contain a path, query, or fragment.")

    try:
        port = parts.port or OLLAMA_DEFAULT_PORT
    except ValueError as exc:
        raise BrainConfigError(f"Invalid port in Ollama host {host!r}.") from exc

    hostname = parts.hostname
    if ":" in hostname:
        hostname = f"[{hostname}]"
    return urlunsplit((parts.scheme, f"{hostname}:{port}", "", "", ""))


def is_loopback_host(host: str) -> bool:
    """Return True only for localhost or a loopback IP address."""

    hostname = urlsplit(normalize_host(host)).hostname or ""
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


class Brain:
    """Small, testable wrapper around ``ollama.Client``.

    A client can be injected for tests. Production clients are created lazily
    so importing this module never touches the network.
    """

    def __init__(
        self,
        config: BrainConfig | None = None,
        *,
        client: Any | None = None,
    ) -> None:
        self.config = config or BrainConfig.from_env()
        self._client = client
        self._ready_models: set[str] = set()
        self._thinking_support: dict[str, bool] = {}

    def __enter__(self) -> "Brain":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP client, if one was created."""

        if self._client is not None:
            close = getattr(self._client, "close", None)
            if callable(close):
                close()
            self._client = None
        self._ready_models.clear()

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        try:
            import httpx
            import ollama
        except ImportError as exc:
            raise OllamaUnavailableError(
                "The Ollama Python package is not installed.",
                hint="Install it with `pip install ollama`.",
            ) from exc

        timeout = httpx.Timeout(
            connect=self.config.connect_timeout,
            read=self.config.timeout,
            write=30.0,
            pool=5.0,
        )
        self._client = ollama.Client(
            host=self.config.host,
            timeout=timeout,
            # A local-only client must not inherit HTTP(S)_PROXY settings or
            # follow a redirect that could move a prompt to another host.
            trust_env=False,
            follow_redirects=False,
        )
        return self._client

    def status(self) -> BrainStatus:
        """Check connectivity and model availability without raising."""

        try:
            models = self._list_models()
        except BrainError as exc:
            return BrainStatus(
                host=self.config.host,
                model=self.config.model,
                reachable=False,
                model_available=False,
                error=str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive boundary
            return BrainStatus(
                host=self.config.host,
                model=self.config.model,
                reachable=False,
                model_available=False,
                error=f"Unexpected error while contacting Ollama: {exc}",
            )

        return BrainStatus(
            host=self.config.host,
            model=self.config.model,
            reachable=True,
            model_available=self._model_available(self.config.model, models),
            models=models,
        )

    def check_connection(self) -> BrainStatus:
        """Alias for :meth:`status` used by callers that only need a probe."""

        return self.status()

    def ensure_ready(self, model: str | None = None, *, force: bool = False) -> None:
        """Raise a friendly error unless Ollama and the model are available."""

        selected = model or self.config.model
        if not force and selected in self._ready_models:
            return
        models = self._list_models()
        if not self._model_available(selected, models):
            raise ModelNotFoundError(selected, models)
        self._ready_models.add(selected)

    def stream_chat(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        model: str | None = None,
        system: str | None = None,
        temperature: float | None = None,
        num_predict: int | None = None,
        think: bool | None = None,
    ) -> Iterator[StreamChunk]:
        """Stream a chat response as incremental :class:`StreamChunk` objects.

        The caller can stop iterating at any time; the underlying stream is
        closed in ``finally``. A failure after text was emitted raises
        :class:`StreamInterruptedError` with the partial text attached.
        """

        selected = model or self.config.model
        prepared = self._prepare_messages(messages, system)
        _validate_stream_overrides(
            temperature=temperature,
            num_predict=num_predict,
            think=think,
        )
        self.ensure_ready(selected)

        options = {
            "temperature": (
                self.config.temperature if temperature is None else float(temperature)
            ),
            "num_ctx": self.config.num_ctx,
            "num_predict": (
                self.config.num_predict if num_predict is None else int(num_predict)
            ),
        }
        request: dict[str, Any] = {
            "model": selected,
            "messages": prepared,
            "stream": True,
            "options": options,
        }
        think_value = self._resolve_think(selected, think)
        if think_value is not None:
            request["think"] = think_value

        client = self._get_client()
        try:
            raw_stream = client.chat(**request)
        except Exception as exc:
            mapped = self._map_error(exc, selected)
            if mapped is not None:
                raise mapped from exc
            raise ModelResponseError(
                "Ollama rejected the chat request.",
                hint="Check `ollama list` and retry. Use --debug for details.",
            ) from exc

        partial: list[str] = []
        produced = False
        try:
            for raw in raw_stream:
                chunk = self._to_chunk(raw)
                if chunk.content:
                    produced = True
                    partial.append(chunk.content)
                yield chunk
        except (GeneratorExit, KeyboardInterrupt):
            raise
        except BrainError:
            raise
        except Exception as exc:
            mapped = self._map_error(exc, selected)
            hint = (
                mapped.hint
                if mapped is not None and mapped.hint
                else "Check `ollama list` and retry. Use --debug for details."
            )
            raise StreamInterruptedError(
                "The model stream ended before it completed.",
                partial_text="".join(partial),
                hint=hint,
            ) from exc
        finally:
            close = getattr(raw_stream, "close", None)
            if callable(close):
                close()

        if not produced:
            raise EmptyResponseError(
                "The model returned no text.",
                hint="Try a shorter prompt, or check that the model is working with `ollama run`.",
            )

    def complete_chat(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        model: str | None = None,
        system: str | None = None,
        temperature: float | None = None,
        num_predict: int | None = None,
        think: bool | None = None,
    ) -> ChatResult:
        """Collect a streamed response into a single result."""

        chunks = list(
            self.stream_chat(
                messages,
                model=model,
                system=system,
                temperature=temperature,
                num_predict=num_predict,
                think=think,
            )
        )
        text = "".join(chunk.content for chunk in chunks)
        thinking = "".join(chunk.thinking or "" for chunk in chunks) or None
        final = chunks[-1]
        for chunk in reversed(chunks):
            if chunk.done:
                final = chunk
                break
        return ChatResult(
            text=text,
            model=model or self.config.model,
            thinking=thinking,
            eval_count=final.eval_count,
            eval_duration_ns=final.eval_duration_ns,
        )

    def _list_models(self) -> tuple[str, ...]:
        client = self._get_client()
        try:
            response = client.list()
        except Exception as exc:
            mapped = self._map_error(exc, self.config.model)
            if mapped is not None:
                raise mapped from exc
            raise BrainError(
                "Could not list Ollama models.",
                hint="Check that Ollama is running with `ollama list`.",
            ) from exc
        return self._extract_model_names(response)

    @staticmethod
    def _extract_model_names(response: Any) -> tuple[str, ...]:
        raw_models = getattr(response, "models", None)
        if raw_models is None and isinstance(response, Mapping):
            raw_models = response.get("models", ())

        names: list[str] = []
        for item in raw_models or ():
            if isinstance(item, str):
                name = item
            else:
                name = getattr(item, "model", None) or getattr(item, "name", None)
                if name is None and isinstance(item, Mapping):
                    name = item.get("model") or item.get("name")
            if name:
                names.append(str(name))
        return tuple(sorted(set(names)))

    @staticmethod
    def _model_key(name: str) -> str:
        value = name.strip().lower()
        if value and ":" not in value:
            value = f"{value}:latest"
        return value

    @classmethod
    def _model_available(cls, model: str, models: Sequence[str]) -> bool:
        wanted = cls._model_key(model)
        return any(cls._model_key(item) == wanted for item in models)

    def _resolve_think(self, model: str, think: bool | None) -> bool | None:
        if think is not None:
            return think
        if self.config.think is not None:
            return self.config.think
        return False if self.supports_thinking(model) else None

    def supports_thinking(self, model: str) -> bool:
        """Return whether the installed model advertises thinking support."""

        if model in self._thinking_support:
            return self._thinking_support[model]
        try:
            response = self._get_client().show(model)
            capabilities = getattr(response, "capabilities", None)
            if capabilities is None and isinstance(response, Mapping):
                capabilities = response.get("capabilities")
            supported = "thinking" in (capabilities or ())
        except Exception:
            supported = False
        self._thinking_support[model] = supported
        return supported

    @staticmethod
    def _prepare_messages(
        messages: Sequence[Mapping[str, Any]],
        system: str | None,
    ) -> list[dict[str, str]]:
        if messages is None:
            raise InvalidMessageError("At least one chat message is required.")

        prepared: list[dict[str, str]] = []
        if system and system.strip():
            prepared.append({"role": "system", "content": system.strip()})

        for index, item in enumerate(messages):
            if not isinstance(item, Mapping):
                raise InvalidMessageError(f"Message {index} is not a mapping.")
            role = str(item.get("role", "")).strip()
            content = item.get("content")
            if role not in {"system", "user", "assistant"}:
                raise InvalidMessageError(
                    f"Message {index} has unsupported role {role!r}.",
                    hint="Use system, user, or assistant.",
                )
            if not isinstance(content, str) or not content.strip():
                raise InvalidMessageError(f"Message {index} has no text content.")
            prepared.append({"role": role, "content": content})

        if not prepared:
            raise InvalidMessageError("At least one chat message is required.")
        return prepared

    @staticmethod
    def _to_chunk(raw: Any) -> StreamChunk:
        if isinstance(raw, Mapping):
            message = raw.get("message") or {}
            content = (
                message.get("content")
                if isinstance(message, Mapping)
                else getattr(message, "content", None)
            )
            thinking = (
                message.get("thinking")
                if isinstance(message, Mapping)
                else getattr(message, "thinking", None)
            )
            done = bool(raw.get("done", False))
            eval_count = raw.get("eval_count")
            eval_duration = raw.get("eval_duration")
        else:
            message = getattr(raw, "message", None)
            content = getattr(message, "content", None)
            thinking = getattr(message, "thinking", None)
            done = bool(getattr(raw, "done", False))
            eval_count = getattr(raw, "eval_count", None)
            eval_duration = getattr(raw, "eval_duration", None)

        if content is None:
            content = ""
        if not isinstance(content, str):
            raise ModelResponseError("Ollama returned non-text message content.")
        if thinking is not None and not isinstance(thinking, str):
            thinking = str(thinking)
        return StreamChunk(
            content=content,
            thinking=thinking,
            done=done,
            eval_count=eval_count if isinstance(eval_count, int) else None,
            eval_duration_ns=eval_duration if isinstance(eval_duration, int) else None,
        )

    @staticmethod
    def _response_error(exc: Exception) -> Any | None:
        try:
            from ollama import ResponseError
        except ImportError:  # pragma: no cover - dependency is declared
            return None
        return exc if isinstance(exc, ResponseError) else None

    def _map_error(self, exc: Exception, model: str | None = None) -> BrainError | None:
        if isinstance(exc, BrainError):
            return exc

        try:
            import httpx
        except ImportError:  # pragma: no cover - dependency is declared
            httpx = None  # type: ignore[assignment]

        if isinstance(exc, ConnectionError):
            return OllamaUnavailableError(
                f"Cannot reach Ollama at {self.config.host}.",
                hint=(
                    "Start it with `ollama serve`, then verify with `ollama list`. "
                    "PHANTOM does not start services automatically."
                ),
            )
        if isinstance(exc, TimeoutError) or (
            httpx is not None and isinstance(exc, httpx.TimeoutException)
        ):
            return BrainTimeoutError(
                "Ollama did not answer before the timeout.",
                hint=(
                    "The local model may still be loading. Increase the timeout, "
                    "use a smaller model, or preload it with `ollama run <model>`."
                ),
            )
        if httpx is not None and isinstance(exc, httpx.ConnectError):
            return OllamaUnavailableError(
                f"Cannot reach Ollama at {self.config.host}.",
                hint="Start it with `ollama serve`, then verify with `ollama list`.",
            )
        if isinstance(exc, OSError):
            return OllamaUnavailableError(
                f"Cannot reach Ollama at {self.config.host}.",
                hint="Start it with `ollama serve`, then verify with `ollama list`.",
            )

        response_error = self._response_error(exc)
        if response_error is not None:
            status = getattr(response_error, "status_code", None)
            if status == 404:
                return ModelNotFoundError(model or self.config.model)
            return ModelResponseError(
                f"Ollama rejected the request (HTTP {status}).",
                hint="Check `ollama list`, the model name, and the context size.",
            )
        return None


def _validate_stream_overrides(
    *,
    temperature: float | None,
    num_predict: int | None,
    think: bool | None,
) -> None:
    if temperature is not None:
        try:
            value = float(temperature)
        except (TypeError, ValueError) as exc:
            raise BrainConfigError("temperature must be a number.") from exc
        if not 0.0 <= value <= 2.0:
            raise BrainConfigError("temperature must be between 0.0 and 2.0.")
    if num_predict is not None:
        if (
            not isinstance(num_predict, int)
            or isinstance(num_predict, bool)
            or num_predict <= 0
        ):
            raise BrainConfigError("num_predict must be a positive integer.")
    if think not in (None, True, False):
        raise BrainConfigError("think must be True, False, or None.")


def _env_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _env_float(value: str | None, default: float, name: str) -> float:
    if value is None or not value.strip():
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise BrainConfigError(f"{name} must be a number.") from exc


def _env_int(value: str | None, default: int, name: str) -> int:
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise BrainConfigError(f"{name} must be an integer.") from exc
