"""Private, loopback-only connectivity checks for the optional Ollama assistant."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


OLLAMA_BASE_URL = "http://127.0.0.1:11434"
STATUS_TIMEOUT_SECONDS = 2
MAX_STATUS_RESPONSE_BYTES = 1_000_000
MAX_CHAT_RESPONSE_BYTES = 64_000
CHAT_TIMEOUT_SECONDS = 90


class _NoRedirectHandler(HTTPRedirectHandler):
    """Do not let a local service redirect PFOS requests to a remote host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# Do not inherit HTTP(S)_PROXY settings for this connection. The destination is
# deliberately fixed to loopback, and Ollama must not be reachable through a proxy.
_LOCAL_OPENER = build_opener(ProxyHandler({}), _NoRedirectHandler())


class OllamaUnavailable(Exception):
    """A safe, non-sensitive reason the configured local model could not answer."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def get_ollama_status(enabled: bool, configured_model: str | None) -> dict[str, bool | str]:
    """Return safe readiness information without exposing model or household data."""
    model = configured_model.strip() if configured_model else ""
    result: dict[str, bool | str] = {
        "enabled": enabled,
        "configured": bool(model) and len(model) <= 200,
        "reachable": False,
        "model_available": False,
        "ready": False,
        "processing_location": "pfos_api_host",
        "reason": "disabled" if not enabled else "model_not_configured",
    }

    if not enabled or not model or len(model) > 200:
        return result

    request = Request(
        f"{OLLAMA_BASE_URL}/api/tags",
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with _LOCAL_OPENER.open(request, timeout=STATUS_TIMEOUT_SECONDS) as response:
            payload = response.read(MAX_STATUS_RESPONSE_BYTES + 1)
        if len(payload) > MAX_STATUS_RESPONSE_BYTES:
            raise ValueError("Ollama status response exceeded the size limit")
        decoded = json.loads(payload)
        models = decoded.get("models") if isinstance(decoded, dict) else None
        if not isinstance(models, list):
            raise ValueError("Ollama returned an invalid model list")
    except (HTTPError, URLError, OSError, TimeoutError, ValueError, UnicodeError):
        result["reason"] = "unavailable"
        return result

    available_names = {
        name
        for entry in models
        if isinstance(entry, dict)
        for name in (entry.get("name"), entry.get("model"))
        if isinstance(name, str)
    }
    model_available = model in available_names
    result.update(
        {
            "reachable": True,
            "model_available": model_available,
            "ready": model_available,
            "reason": "ready" if model_available else "model_unavailable",
        }
    )
    return result


def chat_with_ollama(
    configured_model: str | None,
    messages: list[dict[str, str]],
) -> str:
    """Send a bounded help conversation to the explicitly configured local model."""
    status = get_ollama_status(True, configured_model)
    if not status["ready"]:
        raise OllamaUnavailable(str(status["reason"]))

    model = configured_model.strip()  # readiness guarantees a configured string
    body = json.dumps(
        {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"num_predict": 512},
        }
    ).encode("utf-8")
    request = Request(
        f"{OLLAMA_BASE_URL}/api/chat",
        data=body,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _LOCAL_OPENER.open(request, timeout=CHAT_TIMEOUT_SECONDS) as response:
            payload = response.read(MAX_CHAT_RESPONSE_BYTES + 1)
        if len(payload) > MAX_CHAT_RESPONSE_BYTES:
            raise ValueError("Ollama chat response exceeded the size limit")
        decoded = json.loads(payload)
        message = decoded.get("message") if isinstance(decoded, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip() or len(content) > 16_000:
            raise ValueError("Ollama returned an invalid chat response")
        return content.strip()
    except HTTPError as error:
        raise OllamaUnavailable("model_unavailable" if error.code == 404 else "unavailable") from None
    except (URLError, OSError, TimeoutError, ValueError, UnicodeError):
        raise OllamaUnavailable("unavailable") from None


def chat_turn_with_ollama(
    configured_model: str | None,
    messages: list[dict],
    tools: list[dict],
) -> dict:
    """Request one bounded local assistant turn, including optional tool calls."""
    status = get_ollama_status(True, configured_model)
    if not status["ready"]:
        raise OllamaUnavailable(str(status["reason"]))

    model = configured_model.strip()
    body = json.dumps({
        "model": model,
        "messages": messages,
        "tools": tools,
        "stream": False,
        "options": {"num_predict": 512},
    }).encode("utf-8")
    request = Request(
        f"{OLLAMA_BASE_URL}/api/chat",
        data=body,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _LOCAL_OPENER.open(request, timeout=CHAT_TIMEOUT_SECONDS) as response:
            payload = response.read(MAX_CHAT_RESPONSE_BYTES + 1)
        if len(payload) > MAX_CHAT_RESPONSE_BYTES:
            raise ValueError("Ollama chat response exceeded the size limit")
        decoded = json.loads(payload)
        message = decoded.get("message") if isinstance(decoded, dict) else None
        if not isinstance(message, dict):
            raise ValueError("Ollama returned an invalid chat response")
        content = message.get("content", "")
        calls = message.get("tool_calls", [])
        if not isinstance(content, str) or len(content) > 16_000:
            raise ValueError("Ollama returned invalid message content")
        if not isinstance(calls, list) or len(calls) > 1:
            raise ValueError("Ollama returned too many tool calls")
        return {"role": "assistant", "content": content, "tool_calls": calls}
    except HTTPError as error:
        raise OllamaUnavailable("model_unavailable" if error.code == 404 else "unavailable") from None
    except (URLError, OSError, TimeoutError, ValueError, UnicodeError):
        raise OllamaUnavailable("unavailable") from None
