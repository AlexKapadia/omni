"""Exact per-model cost arithmetic for the router ledger (Decimal, no floats).

Purpose: turn provider-reported token counts into an EXACT estimated USD
cost. This is a deterministic path (claude.md §3.11): a single unit of
arithmetic error is unacceptable, so everything is ``Decimal`` end-to-end —
floats never enter, costs are stored as exact decimal strings, and sums are
performed in Decimal by the ledger repository.
Pipeline position: called by ``engine.router.fallback_executor`` when
recording each ledger row; the Settings screen reads the summed results.

Prices are LIST prices (USD per 1,000,000 tokens) at the time of writing —
a data table, so a price change is a one-line edit, never a code change.
"""

from decimal import Decimal

from engine.router.routing_table import (
    ANTHROPIC_MODEL,
    AZURE_OPENAI_DEFAULT_MODEL,
    GEMINI_FLASH_MODEL,
    GEMINI_PRO_MODEL,
    GROQ_FAST_MODEL,
    LMSTUDIO_DEFAULT_MODEL,
    OLLAMA_DEFAULT_MODEL,
    OPENAI_MINI_MODEL,
    OPENROUTER_DEFAULT_MODEL,
)

_TOKENS_PER_PRICE_UNIT = Decimal(1_000_000)


class UnknownModelPricingError(Exception):
    """Raised for a model with no price row — fail closed, never guess $0."""

    def __init__(self, model: str) -> None:
        super().__init__(f"no pricing entry for model {model!r}")


# USD per 1M tokens: (input price, output price). Decimal FROM STRINGS —
# constructing from float would bake in binary representation error.
MODEL_PRICES_USD_PER_MILLION: dict[str, tuple[Decimal, Decimal]] = {
    GROQ_FAST_MODEL: (Decimal("0.59"), Decimal("0.79")),
    GEMINI_FLASH_MODEL: (Decimal("0.30"), Decimal("2.50")),
    GEMINI_PRO_MODEL: (Decimal("1.25"), Decimal("10.00")),
    ANTHROPIC_MODEL: (Decimal("3.00"), Decimal("15.00")),
    OPENAI_MINI_MODEL: (Decimal("0.15"), Decimal("0.60")),
    OLLAMA_DEFAULT_MODEL: (Decimal("0.00"), Decimal("0.00")),
    OPENROUTER_DEFAULT_MODEL: (Decimal("0.15"), Decimal("0.60")),
    AZURE_OPENAI_DEFAULT_MODEL: (Decimal("0.15"), Decimal("0.60")),
    LMSTUDIO_DEFAULT_MODEL: (Decimal("0.00"), Decimal("0.00")),
}


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> Decimal:
    """Exact cost: prompt*in_price/1M + completion*out_price/1M.

    Both divisions are by a power of 10, so the result is always a finite,
    exact Decimal — no rounding occurs anywhere on this path.

    Raises ``UnknownModelPricingError`` for unpriced models and
    ``ValueError`` for negative token counts (fail closed on nonsense
    inputs rather than logging a negative cost).
    """
    if prompt_tokens < 0 or completion_tokens < 0:
        raise ValueError(
            f"token counts must be non-negative, got prompt={prompt_tokens} "
            f"completion={completion_tokens}"
        )
    prices = MODEL_PRICES_USD_PER_MILLION.get(model)
    if prices is None:
        raise UnknownModelPricingError(model)
    input_price, output_price = prices
    prompt_cost = Decimal(prompt_tokens) * input_price / _TOKENS_PER_PRICE_UNIT
    completion_cost = Decimal(completion_tokens) * output_price / _TOKENS_PER_PRICE_UNIT
    return prompt_cost + completion_cost
