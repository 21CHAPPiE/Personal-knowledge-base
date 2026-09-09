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

    def chat(self, prompt: str, max_tokens: int = 300, temperature: float = 0.2,
             enable_thinking: bool = True) -> str:
        # enable_thinking=False (llama.cpp/vLLM chat_template_kwargs extension
        # for Qwen3): without it, a reasoning model spends max_tokens on
        # reasoning_content first and content comes back empty once a task is
        # complex enough to eat the whole budget thinking — confirmed twice on
        # this deployment (see kb lesson id=21). Off by default here because
        # summarize/suggest_tags already work within their tuned budget and
        # changing their output style isn't this method's job; callers whose
        # task is reasoning-heavy enough to be at risk (structured extraction
        # over several items, say) should pass False explicitly.
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if not enable_thinking:
            payload["chat_template_kwargs"] = {"enable_thinking": False}
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

    def find_logic_groups(self, items: List[dict], context: Optional[str] = None) -> List[dict]:
        """Group items whose underlying logic/cause is shared, not merely their
        topic. Structural similarity (relations: who caused what, who owes
        whom) is the signal, not surface similarity (same person, same place)
        — see docs/architecture.md's discussion of this distinction. Only
        surfaces groups of 2+ items with an explicit stated reason; the caller
        turns each into a proposal for a person to accept or dismiss, never a
        silent rewrite.
        """
        listing = "\n".join(
            "#{}: {}\n{}".format(it["id"], it["title"], it["excerpt"]) for it in items
        )
        heading = "在《{}》里的一组条目".format(context) if context else "一组知识条目"
        prompt = (
            "下面是{}，每条有编号、标题、摘录。\n\n{}\n\n"
            "找出其中哪几条事件背后是同一个底层逻辑/因果驱动的（比如都源于同一个动机、"
            "同一条因果链、同一种利益关系），而不是仅仅提到同一个人名或同一个地点这种表面关联。"
            "每组至少 2 条，最多分 5 组，说不清底层逻辑就不要勉强凑组。\n\n"
            '严格输出 JSON 数组，每个元素形如 '
            '{{"item_ids": [编号,...], "shared_logic": "一句话说清共同的底层逻辑是什么"}}，'
            "找不到任何一组就输出 []，不要输出其他文字。"
        ).format(heading, listing)
        raw = self.chat(prompt, max_tokens=800, enable_thinking=False)
        return self._parse_logic_groups(raw, valid_ids={it["id"] for it in items})

    @staticmethod
    def _parse_logic_groups(raw: str, valid_ids: set) -> List[dict]:
        m = re.search(r"\[.*\]", raw, flags=re.S)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except ValueError:
            return []
        if not isinstance(data, list):
            return []
        groups = []
        for entry in data[:5]:
            if not isinstance(entry, dict):
                continue
            ids = entry.get("item_ids")
            reason = str(entry.get("shared_logic") or "").strip()
            if not isinstance(ids, list) or not reason:
                continue
            ids = sorted({int(i) for i in ids if isinstance(i, (int, float)) and int(i) in valid_ids})
            if len(ids) < 2:
                continue
            groups.append({"item_ids": ids, "shared_logic": reason})
        return groups

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
