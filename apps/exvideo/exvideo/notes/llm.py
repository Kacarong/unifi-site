"""LLM 프로바이더 어댑터.

세 가지 붙이는 방식이 있다.

1. `ollama`   — 로컬 모델. 키도 계정도 필요 없고 토큰 비용 0. 색인처럼 양이
                많고 품질 요구가 낮은 단계의 기본값이다.
2. `claude-cli` — **계정 연동.** 이미 로그인된 Claude Code 를 그대로 불러 쓴다.
                API 키가 필요 없고 구독으로 돌아간다. 정리본 생성의 기본값.
3. `claude` / `gemini` — 순수 API 키 방식. 키가 없으면 조용히 넘어가지 않고
                바로 실패시킨다(엉뚱한 모델로 몰래 대체하지 않는다).

모든 호출은 실제 입력/출력 토큰 수를 돌려준다. 추정치가 아니라
프로바이더가 보고한 값이다.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
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
    # 답변이 한 번에 안 끝나 이어 쓴 횟수. 1 이면 온전한 한 통이다.
    # 2 이상이면 이은 자리에서 몇 줄이 빠졌을 수 있다(실측: 200줄 중 2줄).
    chunks: int = 1


class LLMError(RuntimeError):
    pass


def _join_overlap(head: str, tail: str, window: int = 400) -> str:
    """앞뒤가 겹쳐 나온 만큼 덜어내고 잇는다. 겹침이 없으면 그냥 붙인다."""
    if not head or not tail:
        return head + tail
    for n in range(min(len(head), len(tail), window), 0, -1):
        if head.endswith(tail[:n]):
            return head + tail[n:]
    return head + tail


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


class ClaudeCLIProvider:
    """계정 연동 클로드 — 로그인된 Claude Code 를 그대로 호출한다.

    API 키를 쓰지 않는다. 이미 로그인해 둔 계정(구독)으로 돌아간다.

    Claude Code 를 기본 상태로 부르면 도구 정의와 기본 시스템 프롬프트가 딸려와
    호출마다 38,000 토큰이 먼저 붙는다(실측). 여기서는 코딩 에이전트가 아니라
    글 쓰는 모델 하나만 있으면 되므로 도구·설정·슬래시명령을 전부 끄고 부른다.
    같은 호출이 151 토큰으로 떨어진다(실측).
    """

    name = "claude-cli"

    # PATH 에 없을 때 찾아볼 자리들
    CANDIDATES = (
        "~/.local/bin/claude",
        "~/.claude/local/claude",
        "~/.npm-global/bin/claude",
    )

    def __init__(self, model: str | None = None, binary: str | None = None):
        self.model = model or os.environ.get("EXVIDEO_CLAUDE_CLI_MODEL", "sonnet")
        self.binary = binary or self._find_binary()

    @classmethod
    def _find_binary(cls) -> str:
        explicit = os.environ.get("EXVIDEO_CLAUDE_CLI", "").strip()
        if explicit:
            if not os.path.isfile(explicit):
                raise LLMError(f"EXVIDEO_CLAUDE_CLI 경로에 실행 파일이 없습니다: {explicit}")
            return explicit
        found = shutil.which("claude")
        if found:
            return found
        for cand in cls.CANDIDATES:
            path = os.path.expanduser(cand)
            if os.path.isfile(path):
                return path
        raise LLMError(
            "Claude Code 실행 파일을 찾지 못했습니다. 설치 후 로그인하거나"
            " EXVIDEO_CLAUDE_CLI 에 경로를 지정하세요."
        )

    def complete(self, system: str, user: str, *, json_mode: bool = False,
                 max_tokens: int = 2048) -> LLMResult:
        if json_mode:
            user += "\n\nJSON 객체 하나만 출력하세요. 설명 문장을 앞뒤에 붙이지 마세요."
        # Claude Code 는 스스로 길이를 재지 않아, 분량을 안 알려주면 한없이 길게 쓴다.
        # 실측: 6개 구성을 한 번에 시켰더니 출력만 36,000 토큰이 나왔다.
        user += f"\n\n분량은 {max_tokens} 토큰 안쪽으로 맞추세요."
        cmd = [
            self.binary, "-p",
            "--system-prompt", system,
            "--model", self.model,
            "--tools", "",                 # 도구 정의를 통째로 뺀다
            "--strict-mcp-config",         # 외부 MCP 서버 무시
            "--setting-sources", "",       # 사용자/프로젝트 설정 무시
            "--disable-slash-commands",
            "--no-session-persistence",
            "--max-turns", "1",
            # json 이 아니라 stream-json 인 이유는 _collect_text 주석 참고.
            "--output-format", "stream-json", "--verbose",
        ]
        # 작업 디렉터리에 있는 CLAUDE.md 같은 것이 끼어들지 않도록 빈 곳에서 돈다.
        with tempfile.TemporaryDirectory(prefix="exvideo-claude-") as cwd:
            try:
                proc = subprocess.run(
                    cmd, input=user, cwd=cwd, capture_output=True,
                    text=True, timeout=TIMEOUT,
                )
            except subprocess.TimeoutExpired as exc:
                raise LLMError(f"Claude Code 호출이 {TIMEOUT:.0f}초 안에 끝나지 않았습니다.") from exc
            except OSError as exc:
                raise LLMError(f"Claude Code 실행 실패 ({self.binary}): {exc}") from exc

        if proc.returncode != 0:
            raise LLMError(f"Claude Code 호출 실패(exit {proc.returncode}): "
                           f"{(proc.stderr or proc.stdout).strip()[:400]}")

        text, usage, error, chunks = self._collect_text(proc.stdout)
        if error:
            raise LLMError(f"Claude Code 오류: {error[:400]}")
        if not text.strip():
            raise LLMError("Claude Code 가 빈 응답을 돌려줬습니다.")

        # 캐시로 읽힌 토큰도 입력으로 센다. 그래야 실제 투입량이 보인다.
        input_tokens = (int(usage.get("input_tokens") or 0)
                        + int(usage.get("cache_creation_input_tokens") or 0)
                        + int(usage.get("cache_read_input_tokens") or 0))
        return LLMResult(
            text=text,
            input_tokens=input_tokens,
            output_tokens=int(usage.get("output_tokens") or 0),
            provider=self.name,
            model=self.model,
            chunks=chunks,
        )

    @staticmethod
    def _collect_text(stdout: str) -> tuple[str, dict, str, int]:
        """스트림에서 답변 전체를 이어 붙인다.

        긴 글은 한 번의 응답에 다 담기지 않는다. 그러면 Claude Code 가 알아서
        이어 쓰는데, `--output-format json` 의 `result` 에는 **마지막 조각만**
        담긴다. 실측: 200줄을 시켰더니 1~50 / 50~97 / 97~146 세 조각으로 쪼개졌고
        `result` 는 마지막 조각(97~146)뿐이었다. 그대로 쓰면 글의 앞부분이
        소리 없이 사라진다. 그래서 조각을 전부 모아 직접 잇는다.

        이어 쓸 때 경계의 몇 글자가 겹쳐 나오므로(…49번째 줄\\n50번째 / 50번째 줄…)
        겹친 만큼 덜어내고 붙인다. 다만 겹치지 않고 **벌어지는** 경우도 있어
        (실측: 200줄 중 99·100 두 줄이 빠졌다) 이어 쓴 횟수를 함께 돌려준다.
        호출부는 이 값으로 사용자에게 알린다. 조용히 넘기면 구멍 난 정리본을
        멀쩡한 것으로 착각하게 된다.
        """
        text, usage, error, chunks = "", {}, "", 0
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = event.get("type")
            if kind == "assistant":
                chunk = "".join(
                    b.get("text", "")
                    for b in (event.get("message") or {}).get("content") or []
                    if b.get("type") == "text"
                )
                if chunk.strip():
                    text = _join_overlap(text, chunk)
                    chunks += 1
            elif kind == "result":
                usage = event.get("usage") or {}
                if event.get("is_error"):
                    error = str(event.get("result") or "알 수 없는 오류")
        return text, usage, error, max(1, chunks)


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


PROVIDERS = {
    "ollama": OllamaProvider,
    "claude-cli": ClaudeCLIProvider,
    "claude": ClaudeProvider,
    "gemini": GeminiProvider,
}


LABELS = {
    "ollama": "로컬 모델 — 계정도 키도 필요 없음",
    "claude-cli": "클로드 — 계정 연동 (로그인된 Claude Code 사용)",
    "claude": "클로드 — API 키",
    "gemini": "제미나이 — API 키",
}


def get_provider(name: str | None = None, model: str | None = None):
    key = (name or os.environ.get("EXVIDEO_LLM") or "ollama").lower()
    if key not in PROVIDERS:
        raise LLMError(f"모르는 프로바이더: {key} (쓸 수 있는 값: {', '.join(PROVIDERS)})")
    return PROVIDERS[key](model=model)


def availability() -> list[dict]:
    """지금 이 컴퓨터에서 실제로 쓸 수 있는 프로바이더만 골라낼 수 있게 상태를 알려준다.

    생성자가 키/실행파일을 확인하므로, 만들어지면 대체로 준비된 것이다.
    올라마만 예외 — 설치돼 있어도 데몬이 꺼져 있을 수 있어 한 번 두드려 본다.
    """
    out = []
    for key, cls in PROVIDERS.items():
        row = {"id": key, "label": LABELS.get(key, key), "ready": True, "reason": "", "model": ""}
        try:
            provider = cls()
            row["model"] = provider.model
            if key == "ollama":
                try:
                    httpx.get(f"{provider.host}/api/tags", timeout=2.0).raise_for_status()
                except httpx.HTTPError as exc:
                    row.update(ready=False, reason=f"Ollama 가 응답하지 않습니다 ({exc.__class__.__name__})")
        except LLMError as exc:
            row.update(ready=False, reason=str(exc))
        out.append(row)
    return out


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
