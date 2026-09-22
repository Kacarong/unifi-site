"""LLM 프로바이더 어댑터.

기본값은 로컬 Ollama(qwen2.5:7b) — API 키 없이 돌아가고 토큰 비용이 0 이다.
클로드·제미나이는 키가 있을 때만 붙는다. 키가 없으면 조용히 넘어가지 않고
바로 실패시킨다(엉뚱한 모델로 몰래 대체하지 않는다).

모든 호출은 실제 입력/출력 토큰 수를 돌려준다. 추정치가 아니라
프로바이더가 보고한 값이다.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

import httpx

TIMEOUT = float(os.environ.get("EXVIDEO_LLM_TIMEOUT", "900"))


@dataclass
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    provider: str
    model: str


class LLMError(RuntimeError):
    pass


class OllamaProvider:
    """로컬 Ollama. 기본 프로바이더."""

    name = "ollama"

    def __init__(self, model: str | None = None, host: str | None = None, num_ctx: int = 16384):
        self.model = model or os.environ.get("EXVIDEO_OLLAMA_MODEL", "qwen2.5:7b")
        self.host = (host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")
        self.num_ctx = num_ctx

    def complete(self, system: str, user: str, *, json_mode: bool = False,
                 max_tokens: int = 2048) -> LLMResult:
        body = {
            "model": self.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "options": {
                "num_ctx": self.num_ctx,
                "num_predict": max_tokens,
                "temperature": 0.2,
            },
        }
        if json_mode:
            body["format"] = "json"
        try:
            r = httpx.post(f"{self.host}/api/chat", json=body, timeout=TIMEOUT)
            r.raise_for_status()
            d = r.json()
        except httpx.HTTPError as exc:
            raise LLMError(f"Ollama 호출 실패 ({self.host}): {exc}") from exc
        return LLMResult(
            text=d["message"]["content"],
            input_tokens=int(d.get("prompt_eval_count") or 0),
            output_tokens=int(d.get("eval_count") or 0),
            provider=self.name,
            model=self.model,
        )


class ClaudeProvider:
    name = "claude"

    def __init__(self, model: str | None = None, api_key: str | None = None):
        self.model = model or os.environ.get("EXVIDEO_CLAUDE_MODEL", "claude-sonnet-4-5")
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not self.api_key:
            raise LLMError(
                "ANTHROPIC_API_KEY 가 없습니다. 클로드를 쓰려면 API 키가 필요합니다"
                " (클로드 구독은 API 키와 별개입니다)."
            )

    def complete(self, system: str, user: str, *, json_mode: bool = False,
                 max_tokens: int = 2048) -> LLMResult:
        if json_mode:
            user += "\n\nJSON 객체 하나만 출력하세요. 설명 문장을 앞뒤에 붙이지 마세요."
        try:
            r = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": max_tokens,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                },
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            d = r.json()
        except httpx.HTTPError as exc:
            raise LLMError(f"Claude 호출 실패: {exc}") from exc
        text = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")
        usage = d.get("usage", {})
        return LLMResult(
            text=text,
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            provider=self.name,
            model=self.model,
        )


class GeminiProvider:
    name = "gemini"

    def __init__(self, model: str | None = None, api_key: str | None = None):
        self.model = model or os.environ.get("EXVIDEO_GEMINI_MODEL", "gemini-2.5-flash")
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        if not self.api_key:
            raise LLMError("GEMINI_API_KEY 가 없습니다. Google AI Studio 에서 발급받아야 합니다.")

    def complete(self, system: str, user: str, *, json_mode: bool = False,
                 max_tokens: int = 2048) -> LLMResult:
        cfg: dict = {"temperature": 0.2, "maxOutputTokens": max_tokens}
        if json_mode:
            cfg["responseMimeType"] = "application/json"
        try:
            r = httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
                headers={"x-goog-api-key": self.api_key, "content-type": "application/json"},
                json={
                    "systemInstruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": user}]}],
                    "generationConfig": cfg,
                },
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            d = r.json()
        except httpx.HTTPError as exc:
            raise LLMError(f"Gemini 호출 실패: {exc}") from exc
        parts = (d.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts)
        usage = d.get("usageMetadata", {})
        return LLMResult(
            text=text,
            input_tokens=int(usage.get("promptTokenCount") or 0),
            output_tokens=int(usage.get("candidatesTokenCount") or 0),
            provider=self.name,
            model=self.model,
        )


PROVIDERS = {"ollama": OllamaProvider, "claude": ClaudeProvider, "gemini": GeminiProvider}


def get_provider(name: str | None = None, model: str | None = None):
    key = (name or os.environ.get("EXVIDEO_LLM") or "ollama").lower()
    if key not in PROVIDERS:
        raise LLMError(f"모르는 프로바이더: {key} (쓸 수 있는 값: {', '.join(PROVIDERS)})")
    return PROVIDERS[key](model=model)


def parse_json(text: str) -> dict:
    """LLM 이 코드펜스나 잡담을 섞어도 JSON 객체 하나를 건져낸다."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise LLMError(f"JSON 을 찾지 못했습니다: {text[:200]!r}")
    return json.loads(text[start : end + 1])
