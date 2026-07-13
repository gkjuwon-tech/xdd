"""Provider-agnostic LLM client.

The default provider is DeepSeek V4 Flash via its OpenAI-compatible
``/chat/completions`` endpoint — chosen over frontier models for cost and
latency. Any OpenAI-compatible endpoint works by overriding ``base_url`` /
``model``. A deterministic :class:`StubLLMClient` lets the entire agent
pipeline run offline (tests, dry runs) with no API key.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Protocol

import httpx

from xdd.config import LLMSettings

log = logging.getLogger(__name__)


class LLMClient(Protocol):
    def chat(self, system: str, user: str, *, json_mode: bool = False) -> str:
        ...


class DeepSeekClient:
    """OpenAI-compatible chat client (DeepSeek by default)."""

    def __init__(self, settings: LLMSettings) -> None:
        self._s = settings
        if not settings.api_key:
            raise ValueError("LLM api_key is empty; use StubLLMClient for offline runs")

    def chat(self, system: str, user: str, *, json_mode: bool = False) -> str:
        payload: dict = {
            "model": self._s.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self._s.temperature,
            "max_tokens": self._s.max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {
            "Authorization": f"Bearer {self._s.api_key}",
            "Content-Type": "application/json",
        }
        resp = httpx.post(
            f"{self._s.base_url}/chat/completions",
            json=payload,
            headers=headers,
            timeout=self._s.timeout_seconds,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


class StubLLMClient:
    """Deterministic offline stand-in.

    It does not "reason"; it returns structured JSON derived from the prompt so
    the pipeline is exercisable end-to-end without network or spend. The
    orchestrator's real intelligence comes from the live provider; this keeps
    tests hermetic.
    """

    def chat(self, system: str, user: str, *, json_mode: bool = False) -> str:
        role = _detect_role(system)
        if role == "analyst":
            return json.dumps(_stub_analyst(user))
        if role == "skeptic":
            return json.dumps(_stub_skeptic(user))
        if role == "reviewer":
            return json.dumps(_stub_reviewer(user))
        return json.dumps({"note": "stub"})


def build_llm(settings: LLMSettings) -> LLMClient:
    if settings.use_stub or not settings.api_key:
        log.info("using StubLLMClient (offline / no api_key)")
        return StubLLMClient()
    return DeepSeekClient(settings)


# --------------------------------------------------------------------- parsing


def parse_json(text: str) -> dict:
    """Extract the first JSON object from an LLM response, tolerantly."""
    text = text.strip()
    # Strip ```json fences if present.
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fall back to the outermost braces.
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"could not parse JSON from LLM response: {text[:200]!r}")


# --------------------------------------------------------- stub implementations


def _detect_role(system: str) -> str:
    s = system.lower()
    if "skeptic" in s:
        return "skeptic"
    if "reviewer" in s or "post-mortem" in s:
        return "reviewer"
    if "analyst" in s:
        return "analyst"
    return "unknown"


def _extract(user: str, key: str, default: float = 0.0) -> float:
    m = re.search(rf"{key}=([+-]?\d+(?:\.\d+)?)", user)
    return float(m.group(1)) if m else default


def _stub_analyst(user: str) -> dict:
    sent = _extract_sentiment(user)
    ret_1d = _extract(user, "ret_1d", 0.0)
    rsi = _extract(user, "rsi", 50.0)
    # Combine narrative sentiment with a light momentum read.
    score = sent + (0.2 if ret_1d > 0 else -0.2 if ret_1d < 0 else 0)
    if score > 0.15:
        direction = "up"
    elif score < -0.15:
        direction = "down"
    else:
        direction = "neutral"
    conf = min(0.85, 0.5 + abs(score) * 0.4)
    if rsi > 75 and direction == "up":
        conf -= 0.1  # overbought caution
    if rsi < 25 and direction == "down":
        conf -= 0.1
    return {
        "direction": direction,
        "confidence": round(max(0.3, conf), 2),
        "horizon_hours": 48,
        "thesis": f"Stub thesis: aggregate sentiment {sent:+.2f} with 1d return {ret_1d:+.2%}.",
        "supporting_points": ["sentiment and momentum aligned"] if abs(score) > 0.3 else [],
        "risk_factors": ["stubbed reasoning — not a live model read"],
        "citations": [],
    }


def _stub_skeptic(user: str) -> dict:
    sent = _extract_sentiment(user)
    ret_1d = _extract(user, "ret_1d", 0.0)
    priced_in = sent != 0 and ret_1d != 0 and (sent > 0) == (ret_1d > 0) and abs(ret_1d) > 0.03
    return {
        "counterpoints": ["move may already be priced in"] if priced_in else ["thin evidence"],
        "confidence_adjustment": -0.15 if priced_in else -0.05,
        "manipulation_suspected": False,
        "already_priced_in": bool(priced_in),
        "verdict": "priced in" if priced_in else "proceed with caution",
    }


def _stub_reviewer(user: str) -> dict:
    pnl = _extract(user, "realized_pnl_pct", 0.0)
    correct = pnl > 0
    return {
        "was_correct": correct,
        "summary": f"{'Correct' if correct else 'Wrong'} call, pnl {pnl:+.2%}",
        "detail": "Stub post-mortem.",
        "tags": ["stub"],
    }


def _extract_sentiment(user: str) -> float:
    m = re.search(r"sentiment[:=]\s*([+-]?\d+(?:\.\d+)?)", user, re.I)
    return float(m.group(1)) if m else 0.0
