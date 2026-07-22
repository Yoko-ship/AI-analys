"""Provider-abstracted LLM client for the news module.

DeepSeek is OpenAI-wire-compatible, so we drive it through the ``openai`` SDK
with a custom ``base_url`` — the same SDK the analysis engine already uses. The
provider is a config swap: point ``LLM_BASE_URL`` / ``LLM_MODEL`` at OpenAI or a
local gateway and nothing else changes.

Two capabilities the news pipeline needs, both hardened with retry/backoff and
token accounting:
  * ``complete_json`` — one structured-output call (the Layer-A classifier).
  * ``run_tool_loop`` — a bounded function-calling loop (the Layer-B
    ``search_news`` agent): the model proposes tool calls, we execute them, feed
    results back, and cap the number of round-trips so it can never spin.

No repo internals are imported here on purpose: this file is the transport layer
and stays reusable/unit-testable in isolation.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
)

logger = logging.getLogger(__name__)

# --- configuration (env, with safe defaults) --------------------------------
# Provider-agnostic: point LLM_BASE_URL / LLM_MODEL at any OpenAI-compatible
# endpoint (DeepSeek, xAI/Grok, OpenAI, Moonshot). Defaults target Grok's cheap
# fast tier. `deepseek-chat`/`deepseek-reasoner` retire 2026-07-24 if you switch back.
DEFAULT_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.x.ai/v1")
DEFAULT_MODEL = os.getenv("LLM_MODEL", "grok-4-fast")
# LLM_API_KEY is the generic key; provider-named vars are accepted for convenience.
_API_KEY = (
    os.getenv("LLM_API_KEY")
    or os.getenv("XAI_API_KEY")
    or os.getenv("DEEPSEEK_API_KEY")
    or os.getenv("api_key")
)

_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "4"))
_BASE_BACKOFF = float(os.getenv("LLM_BASE_BACKOFF", "1.5"))
_REQUEST_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "60"))

# Exceptions worth retrying: transient rate limits, timeouts, 5xx.
_RETRYABLE = (RateLimitError, APITimeoutError, APIConnectionError)


@dataclass
class Usage:
    """Accumulated token spend across one or more calls."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0

    def add(self, raw: Any) -> None:
        if raw is None:
            return
        self.prompt_tokens += getattr(raw, "prompt_tokens", 0) or 0
        self.completion_tokens += getattr(raw, "completion_tokens", 0) or 0
        self.calls += 1

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def est_cost_usd(self, in_per_m: float = 0.14, out_per_m: float = 0.28) -> float:
        """Rough cost estimate at DeepSeek V4-Flash cache-miss rates."""
        return (self.prompt_tokens * in_per_m + self.completion_tokens * out_per_m) / 1_000_000


@dataclass
class ToolLoopResult:
    text: str
    usage: Usage
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    iterations: int = 0
    hit_iteration_cap: bool = False


class LLMError(RuntimeError):
    """Raised when a call cannot be completed after retries."""


class LLMClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        key = api_key or _API_KEY
        if not key:
            raise LLMError(
                "No LLM API key: set LLM_API_KEY (or XAI_API_KEY / DEEPSEEK_API_KEY) in the environment."
            )
        self.model = model or DEFAULT_MODEL
        self._client = OpenAI(
            api_key=key,
            base_url=base_url or DEFAULT_BASE_URL,
            timeout=_REQUEST_TIMEOUT,
            max_retries=0,  # we own the retry loop below
        )

    # -- low-level call with backoff ----------------------------------------
    def _create(self, **kwargs: Any) -> Any:
        last: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                return self._client.chat.completions.create(model=self.model, **kwargs)
            except _RETRYABLE as exc:
                last = exc
                sleep = _BASE_BACKOFF * (2**attempt)
                logger.warning(
                    "LLM call retryable error (%s), attempt %d/%d, sleeping %.1fs",
                    type(exc).__name__, attempt + 1, _MAX_RETRIES, sleep,
                )
                time.sleep(sleep)
            except APIStatusError as exc:
                # 5xx is transient; 4xx (bad request/auth) is not — fail fast.
                if exc.status_code >= 500:
                    last = exc
                    sleep = _BASE_BACKOFF * (2**attempt)
                    logger.warning("LLM %d, retrying in %.1fs", exc.status_code, sleep)
                    time.sleep(sleep)
                else:
                    raise LLMError(f"LLM request rejected ({exc.status_code}): {exc}") from exc
        raise LLMError(f"LLM call failed after {_MAX_RETRIES} retries: {last}") from last

    # -- structured JSON (Layer A: classifier) ------------------------------
    def complete_json(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 700,
        usage: Usage | None = None,
    ) -> dict[str, Any]:
        """Return the model's JSON object response, parsed and validated once.

        Uses ``response_format=json_object`` so the model must emit valid JSON.
        On a parse failure we retry once with a corrective nudge, then raise.
        """
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        for parse_attempt in range(2):
            resp = self._create(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            if usage is not None:
                usage.add(getattr(resp, "usage", None))
            content = (resp.choices[0].message.content or "").strip()
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                logger.warning("LLM returned non-JSON (attempt %d); nudging", parse_attempt + 1)
                messages.append({"role": "assistant", "content": content})
                messages.append({
                    "role": "user",
                    "content": "That was not valid JSON. Reply with ONLY the JSON object, no prose.",
                })
        raise LLMError("LLM did not return valid JSON after 2 attempts")

    # -- bounded tool loop (Layer B: search_news agent) ---------------------
    def run_tool_loop(
        self,
        system: str,
        user: str,
        tools: list[dict[str, Any]],
        tool_impls: dict[str, Callable[[dict[str, Any]], Any]],
        *,
        max_iters: int = 6,
        temperature: float = 0.2,
        max_tokens: int = 1200,
    ) -> ToolLoopResult:
        """Run an agentic function-calling loop, capped at ``max_iters`` turns.

        The model may call tools in ``tools`` (executed via ``tool_impls`` keyed
        by name); every call is logged. When it stops requesting tools, or the
        cap is hit, its final text is returned. The cap is the hard guarantee
        that the agent cannot loop or run up unbounded cost.
        """
        usage = Usage()
        call_log: list[dict[str, Any]] = []
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        for i in range(max_iters):
            resp = self._create(
                messages=messages,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            usage.add(getattr(resp, "usage", None))
            msg = resp.choices[0].message
            tool_calls = getattr(msg, "tool_calls", None)
            if not tool_calls:
                return ToolLoopResult(
                    text=(msg.content or "").strip(), usage=usage,
                    tool_calls=call_log, iterations=i + 1, hit_iteration_cap=False,
                )
            # Echo the assistant turn (with its tool_calls) before the results.
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id, "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in tool_calls
                ],
            })
            for tc in tool_calls:
                name = tc.function.name
                try:
                    parsed_args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    parsed_args = {}
                impl = tool_impls.get(name)
                logger.info("agent tool call #%d: %s(%s)", len(call_log) + 1, name, parsed_args)
                if impl is None:
                    output: Any = {"error": f"unknown tool {name}"}
                else:
                    try:
                        output = impl(parsed_args)
                    except Exception as exc:  # noqa: BLE001 — surface tool errors to the model
                        logger.exception("tool %s raised", name)
                        output = {"error": str(exc)}
                call_log.append({"tool": name, "args": parsed_args, "result_preview": _preview(output)})
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(output, ensure_ascii=False, default=str),
                })
        # Cap reached mid-tool-use: ask for a final answer with no more tools.
        messages.append({
            "role": "user",
            "content": "Stop searching and give your final answer now, based on what you already found.",
        })
        resp = self._create(messages=messages, temperature=temperature, max_tokens=max_tokens)
        usage.add(getattr(resp, "usage", None))
        return ToolLoopResult(
            text=(resp.choices[0].message.content or "").strip(), usage=usage,
            tool_calls=call_log, iterations=max_iters, hit_iteration_cap=True,
        )


def _preview(obj: Any, limit: int = 300) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        s = str(obj)
    return s if len(s) <= limit else s[:limit] + "…"


_default: LLMClient | None = None


def get_client() -> LLMClient:
    """Process-wide singleton (created lazily so import never needs a key)."""
    global _default
    if _default is None:
        _default = LLMClient()
    return _default
