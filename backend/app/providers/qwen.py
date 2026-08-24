"""Qwen provider via any OpenAI-compatible /chat/completions endpoint."""

import json
import re
from typing import List, Optional

import httpx

from app.providers.base import LLMProvider, STTProvider


class LLMProviderError(Exception):
    pass


class QwenProvider(LLMProvider):
    name = "qwen"

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 30.0):
        if not base_url or not model:
            raise LLMProviderError("QwenProvider requires base_url and model")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def chat(self, prompt: str, max_tokens: int = 300, temperature: float = 0.2) -> str:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        try:
            resp = httpx.post(url, json=payload, headers=self._headers(), timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"request failed: {exc}") from exc
        if resp.status_code != 200:
            raise LLMProviderError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        try:
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        except (ValueError, KeyError, IndexError) as exc:
            raise LLMProviderError(f"unexpected response shape: {exc}") from exc

    # Reasoning models (e.g. qwen3.8-27b-local) spend most of max_tokens on
    # reasoning_content before any answer text; observed 2026-08-24 that a
    # 150-token budget left content="" for tags. 512 covers observed
    # reasoning overhead plus the answer with headroom.
    LLM_MAX_TOKENS = 512

    def summarize(self, title: str, content: str) -> str:
        body = f"标题: {title}\n内容: {content}"[:6000]
        prompt = (
            "用中文把下面这条个人知识压缩成 1-2 句摘要，"
            "只输出摘要本身，不要解释。\n\n" + body
        )
        return self.chat(prompt, max_tokens=self.LLM_MAX_TOKENS)

    def suggest_tags(self, title: str, content: str) -> List[str]:
        body = f"标题: {title}\n内容: {content}"[:6000]
        prompt = (
            "为下面这条个人知识推荐 3-5 个简短标签（中文或英文，每个不超过 12 字符）。"
            '严格输出 JSON 数组，例如 ["a","b"]，不要其他文字。\n\n' + body
        )
        raw = self.chat(prompt, max_tokens=self.LLM_MAX_TOKENS)
        return self._parse_tags(raw)

    @staticmethod
    def _parse_tags(raw: str) -> List[str]:
        m = re.search(r"\[[^\]]*\]", raw, flags=re.S)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except ValueError:
            return []
        if not isinstance(data, list):
            return []
        tags = []
        for t in data[:8]:
            t = str(t).strip()
            if t and t not in tags:
                tags.append(t)
        return tags


class QwenSTTProvider(STTProvider):
    """OpenAI-compatible audio transcription (POST /audio/transcriptions).

    Kept as an adapter: only activated when STT_* env is configured. If the
    endpoint shape differs on a given server, transcribe() returns None and
    the caller keeps the raw audio without a fake transcript.
    """

    name = "qwen-stt"

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60.0):
        if not base_url or not model:
            raise LLMProviderError("QwenSTTProvider requires base_url and model")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def transcribe(self, audio_path: str, mime_type: str) -> Optional[str]:
        url = f"{self.base_url}/audio/transcriptions"
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        with open(audio_path, "rb") as fh:
            data = {"model": self.model}
            files = {"file": (f"audio.{mime_type.split('/')[-1] or 'webm'}", fh, mime_type)}
            try:
                resp = httpx.post(url, data=data, files=files, headers=headers, timeout=self.timeout)
            except httpx.HTTPError:
                return None
        if resp.status_code != 200:
            return None
        try:
            return resp.json().get("text")
        except ValueError:
            return None
