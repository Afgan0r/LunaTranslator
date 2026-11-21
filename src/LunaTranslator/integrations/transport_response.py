"""Validate Responses output and estimate the observed token cost."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from .engine import TranslationError

type JsonObject = dict[str, Any]


@dataclass(frozen=True)
class TranslationResult:
    text: str
    metadata: JsonObject


def usage_counters(response: JsonObject) -> dict[str, int | None]:
    usage: JsonObject = response.get("usage") or {}
    inputs: JsonObject = usage.get("input_tokens_details") or {}
    outputs: JsonObject = usage.get("output_tokens_details") or {}

    def count(value: object) -> int | None:
        return (
            value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
        )

    return {
        "input_tokens": count(usage.get("input_tokens")),
        "cached_tokens": count(inputs.get("cached_tokens")),
        "cache_write_tokens": count(inputs.get("cache_write_tokens")),
        "output_tokens": count(usage.get("output_tokens")),
        "reasoning_tokens": count(outputs.get("reasoning_tokens")),
    }


def estimate_cost(
    model: str, usage: Mapping[str, int | None], service_tier: str = "default"
) -> JsonObject:
    """Tier-aware USD estimate, never an invoice or assumption of free credit.

    Cache writes replace the normal input charge for those tokens. Missing
    counters remain explicit; their absence makes the estimate provisional.
    """
    rates = {
        "gpt-6-astra": (10, 1, 12.5, 50),
        "gpt-5.6-terra": (2, 0.2, 2.5, 12),
        "gpt-6.1-sol": (2, 0.1, 2.5, 10),
        "gpt-6.2-sol": (2, 0.1, 2.5, 10),
        "gpt-6-luna": (0.1, 0.01, 0.125, 0.5),
    }
    if model not in rates:
        raise ValueError("Unsupported pricing model.")
    missing = [
        name
        for name in ("input_tokens", "cached_tokens", "cache_write_tokens", "output_tokens")
        if usage.get(name) is None
    ]
    incoming = usage.get("input_tokens") or 0
    cached = usage.get("cached_tokens") or 0
    written = usage.get("cache_write_tokens") or 0
    output = usage.get("output_tokens") or 0
    normal = max(0, incoming - cached - written)
    ir, cr, wr, out = rates[model]
    long_context = incoming > 272000
    if long_context:
        ir, cr, wr, out = ir * 2, cr * 2, wr * 2, out * 1.5
    multiplier = 2 if service_tier in ("fast", "priority") else 1
    if service_tier not in ("default", "fast", "priority"):
        missing.append("service_tier")
    return {
        "usd": multiplier * (normal * ir + cached * cr + written * wr + output * out) / 1e6,
        "provisional": bool(missing),
        "missing_counters": missing,
        "long_context": long_context,
        "service_tier": service_tier,
        "basis": "fast_price_estimate_not_invoice"
        if multiplier == 2
        else "standard_price_estimate_not_invoice",
    }


def parse_response(
    data: JsonObject,
    pricing_model: str,
    latency_seconds: float,
    requested_service_tier: str = "default",
) -> TranslationResult:
    if data.get("status") != "completed":
        raise TranslationError("incomplete")
    texts: list[str] = []
    output: object = data.get("output") or []
    if not isinstance(output, list):
        raise TranslationError("invalid_response")
    for candidate in cast(list[object], output):
        if not isinstance(candidate, dict):
            raise TranslationError("invalid_response")
        item = cast(JsonObject, candidate)
        if item.get("type") == "message":
            if item.get("role") != "assistant" or item.get("status") not in (None, "completed"):
                raise TranslationError("incomplete")
            content: object = item.get("content") or []
            if not isinstance(content, list):
                raise TranslationError("invalid_response")
            for candidate_block in cast(list[object], content):
                if not isinstance(candidate_block, dict):
                    raise TranslationError("invalid_response")
                block = cast(JsonObject, candidate_block)
                if block.get("type") == "refusal":
                    raise TranslationError("refusal")
                if block.get("type") == "output_text":
                    text = block.get("text")
                    if not isinstance(text, str):
                        raise TranslationError("invalid_response")
                    texts.append(text)
        elif item.get("type") != "reasoning":
            # Tools must never enter this translation workflow.
            raise TranslationError("invalid_response")
    text = "".join(texts)
    if not text.strip():
        raise TranslationError("empty_output")
    counters = usage_counters(data)

    # IDs/model/tier are deliberately filtered against the API's restricted
    # identifier alphabet; no untrusted error text is persisted.
    def safe_identifier(value: object) -> str | None:
        if (
            isinstance(value, str)
            and 0 < len(value) <= 160
            and all(c.isascii() and (c.isalnum() or c in "-_.") for c in value)
        ):
            return value
        return None

    tier = safe_identifier(data.get("service_tier"))
    cost = estimate_cost(pricing_model, counters, tier or requested_service_tier)
    if tier is None and requested_service_tier != "default":
        cost["provisional"] = True
        cost["missing_counters"].append("service_tier")
    metadata = {
        "usage": counters,
        "latency_seconds": latency_seconds,
        "response_id": safe_identifier(data.get("id")),
        "model": safe_identifier(data.get("model")),
        "service_tier": tier,
        "requested_service_tier": requested_service_tier,
        "cost_estimate": cost,
    }
    return TranslationResult(text, metadata)
