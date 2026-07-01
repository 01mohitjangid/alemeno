"""OpenAI LLM integration (assignment §5c/§5d/§5e).

- Batched classification of uncategorised transactions.
- A single narrative-summary call (narrative + risk_level only; the factual
  stats are computed deterministically in the pipeline).
- Retry with exponential backoff on transient errors; the SDK's own retry is
  disabled so tenacity is the single source of truth. Callers catch LLMError to
  mark a batch `llm_failed` and continue.
"""
from __future__ import annotations

import json
import logging

import openai
from openai import OpenAI
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings

logger = logging.getLogger(__name__)

ALLOWED_CATEGORIES = [
    "Food",
    "Shopping",
    "Travel",
    "Transport",
    "Utilities",
    "Cash Withdrawal",
    "Entertainment",
    "Other",
]
_ALLOWED_SET = set(ALLOWED_CATEGORIES)

# Transient failures worth retrying. Auth / bad-request errors are NOT retried
# (they won't succeed on a retry) and propagate immediately.
_RETRYABLE = (
    openai.RateLimitError,
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.InternalServerError,
    json.JSONDecodeError,
)

_client_instance: OpenAI | None = None


class LLMError(Exception):
    """Raised when an LLM call ultimately fails (after retries)."""


def _client() -> OpenAI:
    global _client_instance
    if _client_instance is None:
        # max_retries=0 -> tenacity owns retrying; timeout bounds each attempt.
        _client_instance = OpenAI(
            api_key=settings.openai_api_key, timeout=30.0, max_retries=0
        )
    return _client_instance


@retry(
    reraise=True,
    stop=stop_after_attempt(1 + settings.llm_max_retries),  # 1 try + N retries
    wait=wait_exponential(multiplier=settings.llm_backoff_base, min=1, max=20),
    retry=retry_if_exception_type(_RETRYABLE),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def _chat_json(messages: list[dict]) -> tuple[dict, str]:
    """Call the chat API in JSON mode; return (parsed, raw_text)."""
    resp = _client().chat.completions.create(
        model=settings.openai_model,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0,
    )
    raw = resp.choices[0].message.content or "{}"
    return json.loads(raw), raw


def classify_transactions(items: list[dict]) -> tuple[dict[int, str], str]:
    """Classify a batch. `items` = [{"index": int, "merchant": str, "notes": str}].

    Returns ({index: category}, raw_response). Raises LLMError on failure.
    """
    payload = [
        {"index": it["index"], "merchant": it["merchant"], "notes": it.get("notes", "")}
        for it in items
    ]
    system = (
        "You are a financial transaction classifier. Assign each transaction to "
        "exactly one category from this list: " + ", ".join(ALLOWED_CATEGORIES) + ". "
        "Use the merchant name as the primary signal. Respond with JSON only."
    )
    user = (
        'Classify each transaction. Return JSON exactly like '
        '{"classifications":[{"index":<int>,"category":"<one allowed category>"}]}.\n'
        "Transactions:\n" + json.dumps(payload)
    )
    try:
        parsed, raw = _chat_json(
            [{"role": "system", "content": system}, {"role": "user", "content": user}]
        )
    except Exception as exc:  # noqa: BLE001 - normalise to LLMError for callers
        raise LLMError(f"classification failed: {exc}") from exc

    mapping: dict[int, str] = {}
    for entry in parsed.get("classifications", []):
        idx = entry.get("index")
        cat = entry.get("category")
        if isinstance(idx, int):
            mapping[idx] = cat if cat in _ALLOWED_SET else "Other"
    return mapping, raw


def generate_narrative(stats: dict) -> tuple[str | None, str | None, str]:
    """Produce (narrative, risk_level, raw_response) from computed stats.

    Raises LLMError on failure.
    """
    system = (
        "You are a financial analyst. Given summary statistics for a batch of "
        "transactions, write a concise 2-3 sentence spending narrative and assign "
        "an overall risk_level of 'low', 'medium', or 'high' based on anomalies and "
        "spend concentration. Respond with JSON only: "
        '{"narrative": "<2-3 sentences>", "risk_level": "low|medium|high"}.'
    )
    user = "Summary statistics:\n" + json.dumps(stats, default=str)
    try:
        parsed, raw = _chat_json(
            [{"role": "system", "content": system}, {"role": "user", "content": user}]
        )
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"narrative generation failed: {exc}") from exc

    narrative = parsed.get("narrative")
    risk = parsed.get("risk_level")
    if risk not in ("low", "medium", "high"):
        risk = None
    return narrative, risk, raw
