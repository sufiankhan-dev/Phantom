from __future__ import annotations

from types import SimpleNamespace

import httpx
import ollama
import pytest

from core.brain import (
    Brain,
    BrainConfig,
    BrainConfigError,
    BrainTimeoutError,
    EmptyResponseError,
    ExternalServiceError,
    InvalidMessageError,
    ModelNotFoundError,
    OllamaUnavailableError,
    StreamInterruptedError,
)


def chunk(
    content: str = "",
    *,
    thinking: str | None = None,
    done: bool = False,
    eval_count: int | None = None,
    eval_duration: int | None = None,
):
    return SimpleNamespace(
        message=SimpleNamespace(content=content, thinking=thinking),
        done=done,
        eval_count=eval_count,
        eval_duration=eval_duration,
    )


class FakeStream:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.closed = False

    def __iter__(self):
        return iter(self.chunks)

    def close(self):
        self.closed = True


class FakeClient:
    def __init__(
        self,
        *,
        models=("qwen3:8b",),
        chunks=None,
        capabilities=("completion", "thinking"),
        list_error=None,
        chat_error=None,
        show_error=None,
    ):
        self.models = [SimpleNamespace(model=name) for name in models]
        self.chunks = chunks if chunks is not None else []
        self.capabilities = capabilities
        self.list_error = list_error
        self.chat_error = chat_error
        self.show_error = show_error
        self.calls = []
        self.show_calls = []
        self.closed = False

    def list(self):
        if self.list_error is not None:
            raise self.list_error
        return SimpleNamespace(models=self.models)

    def show(self, model):
        self.show_calls.append(model)
        if self.show_error is not None:
            raise self.show_error
        return SimpleNamespace(capabilities=self.capabilities)

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        if self.chat_error is not None:
            raise self.chat_error
        if hasattr(self.chunks, "close"):
            return self.chunks
        return iter(self.chunks)

    def close(self):
        self.closed = True


def test_default_configuration():
    config = BrainConfig.from_env({})
    assert config.model == "qwen3:8b"
    assert config.host == "http://127.0.0.1:11434"
    assert config.num_ctx == 4096
    assert config.allow_remote is False


def test_environment_overrides_model_and_host():
    config = BrainConfig.from_env(
        {
            "PHANTOM_MODEL": "gemma3:4b",
            "OLLAMA_HOST": "127.0.0.1:12345",
            "PHANTOM_TIMEOUT": "42",
        }
    )
    assert config.model == "gemma3:4b"
    assert config.host == "http://127.0.0.1:12345"
    assert config.timeout == 42.0


def test_host_normalization_and_remote_rejection():
    assert BrainConfig(host="localhost").host == "http://localhost:11434"
    assert BrainConfig(host=":11434").host == "http://127.0.0.1:11434"
    with pytest.raises(ExternalServiceError):
        BrainConfig(host="http://192.168.1.20:11434")
    allowed = BrainConfig(host="http://192.168.1.20:11434", allow_remote=True)
    assert allowed.host == "http://192.168.1.20:11434"


def test_invalid_config_values():
    with pytest.raises(BrainConfigError):
        BrainConfig(model="")
    with pytest.raises(BrainConfigError):
        BrainConfig(model=None)
    with pytest.raises(BrainConfigError):
        BrainConfig(host=123)
    with pytest.raises(BrainConfigError):
        BrainConfig(timeout=0)
    with pytest.raises(BrainConfigError):
        BrainConfig(num_ctx=0)
    with pytest.raises(BrainConfigError):
        BrainConfig(temperature=3.0)


def test_complete_chat_streams_and_builds_request():
    client = FakeClient(
        chunks=[
            chunk("The "),
            chunk("gate ", thinking="checking"),
            chunk(
                "is open.",
                done=True,
                eval_count=4,
                eval_duration=2_000_000_000,
            ),
        ]
    )
    brain = Brain(BrainConfig(model="qwen3:8b"), client=client)

    result = brain.complete_chat(
        [{"role": "user", "content": "Open the gate."}],
        system="You are PHANTOM.",
    )

    assert result.text == "The gate is open."
    assert result.thinking == "checking"
    assert result.eval_count == 4
    assert result.tokens_per_second == 2.0
    assert client.calls[0]["model"] == "qwen3:8b"
    assert client.calls[0]["stream"] is True
    assert client.calls[0]["messages"][0] == {
        "role": "system",
        "content": "You are PHANTOM.",
    }
    assert client.calls[0]["think"] is False
    assert client.calls[0]["options"]["num_ctx"] == 4096
    assert "tools" not in client.calls[0]


def test_stream_chunks_include_thinking():
    client = FakeClient(chunks=[chunk("answer", thinking="reasoning", done=True)])
    brain = Brain(client=client)
    chunks = list(brain.stream_chat([{"role": "user", "content": "hello"}]))
    assert chunks[0].content == "answer"
    assert chunks[0].thinking == "reasoning"
    assert chunks[0].done is True


def test_missing_model_has_pull_instruction():
    client = FakeClient(models=("gemma3:4b",))
    brain = Brain(client=client)
    with pytest.raises(ModelNotFoundError) as exc:
        brain.complete_chat([{"role": "user", "content": "hello"}])
    assert "ollama pull qwen3:8b" in str(exc.value)
    assert exc.value.available == ("gemma3:4b",)


def test_latest_model_name_is_equivalent():
    client = FakeClient(models=("qwen3:latest",), chunks=[chunk("ok", done=True)])
    brain = Brain(BrainConfig(model="qwen3"), client=client)
    assert brain.complete_chat([{"role": "user", "content": "hello"}]).text == "ok"


def test_connection_failure_is_actionable():
    client = FakeClient(list_error=ConnectionError("refused"))
    brain = Brain(client=client)

    status = brain.status()
    assert status.reachable is False
    assert "ollama serve" in (status.error or "")

    with pytest.raises(OllamaUnavailableError) as exc:
        brain.ensure_ready()
    assert "ollama serve" in str(exc.value)


def test_timeout_is_mapped():
    client = FakeClient(list_error=httpx.ReadTimeout("slow"))
    brain = Brain(client=client)
    status = brain.status()
    assert status.reachable is False
    assert "timeout" in (status.error or "").lower()
    with pytest.raises(BrainTimeoutError):
        brain.ensure_ready()


def test_404_response_is_model_not_found():
    client = FakeClient(list_error=ollama.ResponseError("missing", 404))
    brain = Brain(client=client)
    with pytest.raises(ModelNotFoundError):
        brain.ensure_ready()


def test_empty_stream_is_an_error():
    client = FakeClient(chunks=[chunk("", done=True)])
    brain = Brain(client=client)
    with pytest.raises(EmptyResponseError):
        list(brain.stream_chat([{"role": "user", "content": "hello"}]))


def test_midstream_failure_preserves_partial_text():
    def failing_stream():
        yield chunk("partial ")
        raise RuntimeError("connection died")

    client = FakeClient(chunks=failing_stream())
    brain = Brain(client=client)
    with pytest.raises(StreamInterruptedError) as exc:
        list(brain.stream_chat([{"role": "user", "content": "hello"}]))
    assert exc.value.partial_text == "partial "


def test_non_thinking_model_does_not_receive_think_flag():
    client = FakeClient(capabilities=("completion",), chunks=[chunk("ok", done=True)])
    brain = Brain(client=client)
    brain.complete_chat([{"role": "user", "content": "hello"}])
    assert "think" not in client.calls[0]


def test_explicit_think_false_is_honored():
    client = FakeClient(capabilities=(), chunks=[chunk("ok", done=True)])
    brain = Brain(client=client)
    list(brain.stream_chat([{"role": "user", "content": "hello"}], think=False))
    assert client.calls[0]["think"] is False


def test_invalid_stream_overrides_are_rejected_before_network():
    client = FakeClient(chunks=[chunk("never", done=True)])
    brain = Brain(client=client)
    message = [{"role": "user", "content": "hello"}]

    for overrides in (
        {"temperature": 3.0},
        {"temperature": "hot"},
        {"num_predict": 0},
        {"num_predict": -1},
        {"think": "yes"},
    ):
        with pytest.raises(BrainConfigError):
            list(brain.stream_chat(message, **overrides))

    assert client.calls == []


def test_invalid_messages_are_rejected_before_network():
    client = FakeClient(chunks=[chunk("never", done=True)])
    brain = Brain(client=client)
    with pytest.raises(InvalidMessageError):
        list(brain.stream_chat([]))
    with pytest.raises(InvalidMessageError):
        list(brain.stream_chat([{"role": "wizard", "content": "hello"}]))
    with pytest.raises(InvalidMessageError):
        list(brain.stream_chat([{"role": "user", "content": "   "}]))
    assert client.calls == []


def test_status_reports_model_availability():
    client = FakeClient(models=("qwen3:8b", "gemma3:4b"))
    brain = Brain(client=client)
    status = brain.status()
    assert status.reachable is True
    assert status.model_available is True
    assert status.models == ("gemma3:4b", "qwen3:8b")


def test_close_closes_injected_client():
    client = FakeClient()
    brain = Brain(client=client)
    brain.close()
    assert client.closed is True


def test_stream_is_closed_after_consumption():
    stream = FakeStream([chunk("ok", done=True)])
    client = FakeClient(chunks=stream)
    brain = Brain(client=client)
    list(brain.stream_chat([{"role": "user", "content": "hello"}]))
    assert stream.closed is True


def test_show_failure_omits_think_flag():
    client = FakeClient(
        capabilities=(),
        show_error=RuntimeError("show unavailable"),
        chunks=[chunk("ok", done=True)],
    )
    brain = Brain(client=client)
    brain.complete_chat([{"role": "user", "content": "hello"}])
    assert "think" not in client.calls[0]


def test_mapping_show_response_detects_thinking_support():
    class MappingShowClient(FakeClient):
        def show(self, model):
            self.show_calls.append(model)
            return {"capabilities": ["completion", "thinking"]}

    client = MappingShowClient(chunks=[chunk("ok", done=True)])
    brain = Brain(client=client)

    brain.complete_chat([{"role": "user", "content": "hello"}])
    assert client.calls[0]["think"] is False


def test_real_client_disables_proxy_inheritance_and_redirects(monkeypatch):
    captured = {}

    class FakeOllamaClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def close(self):
            pass

    monkeypatch.setattr(ollama, "Client", FakeOllamaClient)
    brain = Brain(BrainConfig(model="qwen3:8b"))

    client = brain._get_client()

    assert isinstance(client, FakeOllamaClient)
    assert captured["host"] == "http://127.0.0.1:11434"
    assert captured["trust_env"] is False
    assert captured["follow_redirects"] is False
    brain.close()


def test_404_for_model_override_names_the_requested_model():
    client = FakeClient(
        models=("qwen3:8b", "custom:1b"),
        chat_error=ollama.ResponseError("missing", 404),
    )
    brain = Brain(BrainConfig(model="qwen3:8b"), client=client)

    with pytest.raises(ModelNotFoundError) as exc:
        brain.complete_chat(
            [{"role": "user", "content": "hello"}],
            model="custom:1b",
        )
    assert "custom:1b" in str(exc.value)
    assert "qwen3:8b" not in str(exc.value)


def test_cancelled_stream_propagates_and_closes():
    class InterruptingStream:
        def __init__(self):
            self.closed = False

        def __iter__(self):
            yield chunk("partial ")
            raise KeyboardInterrupt

        def close(self):
            self.closed = True

    stream = InterruptingStream()
    client = FakeClient(chunks=stream)
    brain = Brain(client=client)

    with pytest.raises(KeyboardInterrupt):
        list(brain.stream_chat([{"role": "user", "content": "hello"}]))
    assert stream.closed is True


def test_remote_host_requires_environment_consent():
    with pytest.raises(ExternalServiceError):
        BrainConfig.from_env({"OLLAMA_HOST": "http://192.168.1.20:11434"})

    allowed = BrainConfig.from_env(
        {
            "OLLAMA_HOST": "http://192.168.1.20:11434",
            "PHANTOM_ALLOW_REMOTE_OLLAMA": "1",
        }
    )
    assert allowed.host == "http://192.168.1.20:11434"
    assert allowed.allow_remote is True
