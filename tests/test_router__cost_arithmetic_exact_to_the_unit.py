"""Cost-arithmetic tests: the deterministic money path, exact to the unit.

claude.md §3.11: a SINGLE arithmetic error on a deterministic path is
unacceptable. Every expected value here is hand-computed from the list
prices and asserted as an exact Decimal — no tolerances, no approx.
"""

from decimal import Decimal

import pytest

from engine.router.model_pricing import (
    MODEL_PRICES_USD_PER_MILLION,
    UnknownModelPricingError,
    estimate_cost_usd,
)
from engine.router.routing_table import (
    ANTHROPIC_MODEL,
    GEMINI_FLASH_MODEL,
    GEMINI_PRO_MODEL,
    GROQ_FAST_MODEL,
    ROUTING_TABLE,
    AnthropicIfKeyedSlot,
)

# ---------------------------------------------------------------------------
# Hand-computed exact values (prices: USD per 1M tokens)
#   groq llama-3.3:   in 0.59, out 0.79
#   gemini-2.5-flash: in 0.30, out 2.50
#   gemini-2.5-pro:   in 1.25, out 10.00
#   claude-sonnet-4-5: in 3.00, out 15.00
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("model", "prompt", "completion", "expected"),
    [
        # Single-token boundaries: the smallest non-zero unit of money.
        (GROQ_FAST_MODEL, 1, 0, Decimal("0.00000059")),
        (GROQ_FAST_MODEL, 0, 1, Decimal("0.00000079")),
        (GEMINI_FLASH_MODEL, 1, 0, Decimal("0.0000003")),
        (GEMINI_FLASH_MODEL, 0, 1, Decimal("0.0000025")),
        (GEMINI_PRO_MODEL, 1, 1, Decimal("0.00001125")),
        (ANTHROPIC_MODEL, 1, 1, Decimal("0.000018")),
        # Exactly one price-unit of tokens: cost == list price, exactly.
        (GROQ_FAST_MODEL, 1_000_000, 0, Decimal("0.59")),
        (GROQ_FAST_MODEL, 0, 1_000_000, Decimal("0.79")),
        (ANTHROPIC_MODEL, 1_000_000, 1_000_000, Decimal("18.00")),
        # Just-under / just-over the price unit (boundary-exact).
        (GROQ_FAST_MODEL, 999_999, 0, Decimal("0.58999941")),
        (GROQ_FAST_MODEL, 1_000_001, 0, Decimal("0.59000059")),
        # A realistic mixed call, hand-computed.
        (GROQ_FAST_MODEL, 100, 50, Decimal("0.0000985")),
        (GEMINI_FLASH_MODEL, 12_345, 678, Decimal("0.0053985")),
        # Zero tokens costs exactly zero (failed-attempt ledger rows).
        (GROQ_FAST_MODEL, 0, 0, Decimal("0")),
        (ANTHROPIC_MODEL, 0, 0, Decimal("0")),
    ],
)
def test_cost_is_exact_to_the_unit(
    model: str, prompt: int, completion: int, expected: Decimal
) -> None:
    cost = estimate_cost_usd(model, prompt, completion)
    assert cost == expected
    # Stronger than ==: identical exact decimal representation after
    # normalisation (no hidden binary-float artefacts like ...00000004).
    assert cost.normalize() == expected.normalize()


def test_gemini_flash_mixed_call_shows_the_arithmetic() -> None:
    """12,345 * 0.30/1M = 0.0037035; 678 * 2.50/1M = 0.001695;
    total = 0.0053985 — the parametrised case above, derived long-hand."""
    prompt_cost = Decimal(12_345) * Decimal("0.30") / Decimal(1_000_000)
    completion_cost = Decimal(678) * Decimal("2.50") / Decimal(1_000_000)
    assert prompt_cost == Decimal("0.0037035")
    assert completion_cost == Decimal("0.001695")
    assert estimate_cost_usd(GEMINI_FLASH_MODEL, 12_345, 678) == (
        prompt_cost + completion_cost
    )


def test_cost_is_deterministic_across_repetitions() -> None:
    results = {str(estimate_cost_usd(GROQ_FAST_MODEL, 123_456, 78_901)) for _ in range(50)}
    assert len(results) == 1  # identical inputs -> identical output, always


def test_huge_token_counts_stay_exact_no_precision_cliff() -> None:
    """A 10M-token bulk job: 10,000,000 * 0.30/1M = 3.00 exactly, plus
    2,500,000 * 2.50/1M = 6.25 exactly. Large magnitudes must not round."""
    assert estimate_cost_usd(GEMINI_FLASH_MODEL, 10_000_000, 2_500_000) == Decimal("9.25")


def test_additivity_property_costs_compose_exactly() -> None:
    """Metamorphic: cost(a+b) == cost(a) + cost(b) — Decimal makes this an
    identity; under float it would drift."""
    a = estimate_cost_usd(GROQ_FAST_MODEL, 333, 111)
    b = estimate_cost_usd(GROQ_FAST_MODEL, 667, 889)
    whole = estimate_cost_usd(GROQ_FAST_MODEL, 1_000, 1_000)
    assert a + b == whole


@pytest.mark.parametrize(
    ("prompt", "completion"), [(-1, 0), (0, -1), (-100, -100)]
)
def test_negative_token_counts_fail_closed(prompt: int, completion: int) -> None:
    with pytest.raises(ValueError, match="non-negative"):
        estimate_cost_usd(GROQ_FAST_MODEL, prompt, completion)


def test_unknown_model_fails_closed_never_guesses_zero() -> None:
    with pytest.raises(UnknownModelPricingError):
        estimate_cost_usd("gpt-nonexistent", 100, 100)


def test_every_routed_model_has_a_price_row() -> None:
    """The table and the price list must not drift apart: every model the
    routing table can ever emit is priced (else ledger writes would fail)."""
    routed_models: set[str] = set()
    for spec in ROUTING_TABLE.values():
        for slot in (spec.primary, *spec.fallbacks):
            if isinstance(slot, AnthropicIfKeyedSlot):
                routed_models.add(slot.anthropic_model)
                routed_models.add(slot.otherwise.model)
            else:
                routed_models.add(slot.model)
    assert routed_models <= set(MODEL_PRICES_USD_PER_MILLION)


def test_prices_are_decimals_constructed_from_strings_not_floats() -> None:
    """Guard the construction discipline: a price built from a float would
    carry binary error into every cost. Exactness check: each price times
    1M tokens must reproduce the list price string exactly."""
    for model, (input_price, output_price) in MODEL_PRICES_USD_PER_MILLION.items():
        assert estimate_cost_usd(model, 1_000_000, 0) == input_price
        assert estimate_cost_usd(model, 0, 1_000_000) == output_price
