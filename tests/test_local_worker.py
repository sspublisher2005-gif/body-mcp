"""The local worker: honest refusals, loopback-only, mocked runtime."""
import json

from body_mcp import local_worker


class FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_runtime(calls, generate=None):
    """A stand-in for urllib.request.urlopen that serves the Ollama HTTP API."""
    generate = generate or {"response": "- a bullet point", "total_duration": 12_000_000}

    def opener(request, timeout=None):
        calls.append(request)
        if request.full_url.endswith("/api/tags"):
            return FakeResponse({"models": [{"name": "qwen3:0.6b", "size": 522_640_096,
                                             "details": {"family": "qwen3"}}]})
        if request.full_url.endswith("/api/generate"):
            return FakeResponse(generate)
        raise AssertionError(f"unexpected URL: {request.full_url}")

    return opener


def test_no_local_model_is_an_honest_refusal(monkeypatch):
    monkeypatch.delenv("BODY_MCP_LOCAL_MODEL", raising=False)
    monkeypatch.delenv("BODY_MCP_OLLAMA_URL", raising=False)
    monkeypatch.setattr(local_worker, "ollama_installed", lambda: False)
    result = local_worker.run("summarise", "some page text")
    assert result["ok"] is False
    assert result["local"] is False
    assert "ollama pull qwen3:0.6b" in result["reason"]
    assert "never downloads" in result["reason"]


def test_the_local_runtime_is_called_and_the_output_comes_back(monkeypatch):
    import urllib.request

    calls = []
    monkeypatch.setattr(local_worker, "ollama_installed", lambda: True)
    monkeypatch.setattr(urllib.request, "urlopen", fake_runtime(calls))
    result = local_worker.run("summarise", "hello world")
    assert result["ok"] is True
    assert result["local"] is True
    assert result["text"] == "- a bullet point"
    assert result["model"] == "qwen3:0.6b"
    assert result["runtime"] == "ollama"
    # the request went to this machine and nowhere else
    assert calls, "the runtime was not called"
    assert calls[0].full_url.startswith("http://127.0.0.1:11434")


def test_it_refuses_a_runtime_that_is_not_on_this_machine(monkeypatch):
    import urllib.request

    calls = []
    monkeypatch.setenv("BODY_MCP_OLLAMA_URL", "http://example.com:11434")
    monkeypatch.setattr(local_worker, "ollama_installed", lambda: True)
    monkeypatch.setattr(urllib.request, "urlopen", fake_runtime(calls))
    result = local_worker.run("summarise", "secret page text")
    assert result["ok"] is False
    assert "only talks to this machine" in result["reason"]
    assert not calls, "nothing may be sent off this machine"


def test_a_configured_gguf_uses_llama_cpp(monkeypatch, tmp_path):
    model = tmp_path / "model.gguf"
    model.write_bytes(b"GGUF")
    monkeypatch.setenv("BODY_MCP_LOCAL_MODEL", str(model))
    seen = {}

    def fake_call(model_path, prompt, text):
        seen["model_path"] = model_path
        seen["prompt"] = prompt
        return {"text": "clean", "duration_ms": 5, "model": "model.gguf",
                "runtime": "llama.cpp"}

    monkeypatch.setattr(local_worker, "_call_llama_cpp", fake_call)
    result = local_worker.run("redact", "my name is Bob")
    assert result["ok"] is True
    assert result["runtime"] == "llama.cpp"
    assert seen["model_path"] == str(model)
    assert "REDACTED" in seen["prompt"]


def test_an_unknown_task_is_refused():
    result = local_worker.run("translate", "hello")
    assert result["ok"] is False
    assert "unknown task" in result["reason"]


def test_empty_text_is_refused():
    result = local_worker.run("summarise", "   ")
    assert result["ok"] is False
    assert "no text" in result["reason"]


def test_status_says_what_is_actually_there(monkeypatch):
    monkeypatch.delenv("BODY_MCP_LOCAL_MODEL", raising=False)
    monkeypatch.setattr(local_worker, "ollama_installed", lambda: False)
    status = local_worker.status()
    assert status["available"] is False
    assert status["ollama_installed"] is False
    assert "nothing is downloaded" in status["note"]


def test_only_loopback_urls_are_accepted():
    assert local_worker.is_loopback("http://127.0.0.1:11434") is True
    assert local_worker.is_loopback("http://localhost:11434") is True
    assert local_worker.is_loopback("http://10.0.0.5:11434") is False
    assert local_worker.is_loopback("https://api.openai.com") is False
