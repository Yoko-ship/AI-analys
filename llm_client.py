"""Shared accounting and errors for subscription-backed Codex news calls."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Usage:
    """Accumulated Codex token usage across one or more classification calls."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_prompt_tokens: int = 0
    calls: int = 0
    model: str = ""
    subscription_prompt_tokens: int = 0
    subscription_completion_tokens: int = 0
    subscription_cached_prompt_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def cache_hit_rate(self) -> float:
        return (self.cached_prompt_tokens / self.prompt_tokens) if self.prompt_tokens else 0.0

    @property
    def subscription_tokens(self) -> int:
        return self.subscription_prompt_tokens + self.subscription_completion_tokens

    def est_cost_usd(
        self,
        in_per_m: float | None = None,
        out_per_m: float | None = None,
        model: str | None = None,
    ) -> float:
        """Return estimated API spend; Codex calls are covered by the subscription."""
        del in_per_m, out_per_m, model
        return 0.0


class LLMError(RuntimeError):
    """Raised when Codex cannot complete a classification call."""
