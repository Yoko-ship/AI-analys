"""Existing subscription-backed Claude or an explicitly configured local Ollama.

Ollama wire contract: https://docs.ollama.com/api/chat (checked 2026-11-23).
Only deployment configuration chooses endpoints; browser/model inputs cannot.
"""
import json
import os
import shutil

from llm_client import LLMError


class UnavailableModel:
    def complete_json(self, *_args, **_kwargs):
        raise LLMError("Marketing model is not configured; complete model setup first.")


class OllamaModel:
    def __init__(self, url, model, timeout=180):
        self.url, self.model, self.timeout = url.rstrip("/"), model, timeout

    def complete_json(self, system, user, *, response_schema=None, max_tokens=6000):
        import requests
        try:
            response = requests.post(f"{self.url}/api/chat", json={
                "model": self.model, "stream": False, "format": response_schema or "json",
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "options": {"temperature": 0, "num_predict": max_tokens},
            }, timeout=self.timeout)
            response.raise_for_status()
            result = response.json()
            if not result.get("done"):
                raise ValueError("Incomplete local generation")
            value = json.loads(result["message"]["content"])
            if not isinstance(value, dict):
                raise ValueError("Structured object required")
            return value
        except (requests.RequestException, ValueError, KeyError, TypeError):
            raise LLMError("Local model unavailable or returned invalid structured output.") from None


def status():
    provider = os.getenv("MARKETING_MODEL_PROVIDER", "claude").strip()
    model = os.getenv("MARKETING_MODEL", "").strip()
    if provider == "ollama":
        return {"provider": provider, "model": model or None, "configured": bool(model), "execution": "local_service",
                "note": "Requires an installed model and a running Ollama service; availability is confirmed by a completed task."}
    if provider == "claude":
        gateway = bool(os.getenv("CLAUDE_GATEWAY_URL") and os.getenv("CLAUDE_GATEWAY_SECRET"))
        executable = shutil.which(os.getenv("CLAUDE_EXECUTABLE", "claude"))
        return {"provider": provider, "model": model or os.getenv("NEWS_CLAUDE_MODEL", "claude-haiku-4-5"),
                "configured": gateway or bool(executable), "execution": "configured_gateway" if gateway else "server_cli",
                "note": "Requires the owner's Claude login. Configuration alone does not prove a successful model call."}
    return {"provider": "disabled", "model": None, "configured": False, "execution": None, "note": "Choose a model provider in the service configuration."}


def get_model():
    config = status()
    if not config["configured"]:
        return UnavailableModel()
    if config["provider"] == "ollama":
        return OllamaModel(os.getenv("MARKETING_OLLAMA_URL", "http://127.0.0.1:11434"), config["model"])
    from claude_client import ClaudeCodeClient, ClaudeGatewayClient
    options = {"model": config["model"], "fallback_model": None, "timeout": 180}
    if config["execution"] == "configured_gateway":
        return ClaudeGatewayClient(os.environ["CLAUDE_GATEWAY_URL"], os.environ["CLAUDE_GATEWAY_SECRET"], retries=1, **options)
    return ClaudeCodeClient(**options)
