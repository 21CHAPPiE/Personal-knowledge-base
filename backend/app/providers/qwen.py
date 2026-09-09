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

    def abstract_patterns(self, items: List[dict]) -> List[dict]:
        """Strip each item down to a structural pattern with the names removed.

        The de-identification is the load-bearing step, not a tidying pass.
        Leave "叶子农" in the label and every later comparison is dominated by
        "same person", which can only ever rediscover one storyline; take the
        names out and a debt crisis in chapter 5 becomes comparable to a
        structurally identical one in chapter 40 with a different cast. This
        is the abstraction half of schema induction — matching happens on
        these labels, never on the raw text.
        """
        listing = "\n\n".join(
            "#{}\n{}\n{}".format(it["id"], it["title"], it["excerpt"]) for it in items)
        prompt = (
            "下面每条是一个事件，含它的动机和因果。\n\n{}\n\n"
            "把每条抽象成一个**去掉具体人名、地名、机构名**的结构模式，格式像："
            "「甲因关联方破产背上债务 → 甲用制度差价变现来还债」"
            "或「乙以利益为饵，把丙引进自己预设的场合」。\n"
            "只保留角色代号（甲乙丙）、动机和因果关系，20-40 字。"
            "抽象到\"两件表面完全不同的事，如果内在结构一样，标签就该一样\"的程度，"
            "但不要泛到\"某人做了某事\"这种一切都能套的废话。\n\n"
            '严格输出 JSON 数组：[{{"id":编号,"pattern":"..."}}]，不要其他文字。'
        ).format(listing)
        raw = self.chat(prompt, max_tokens=1500, enable_thinking=False)
        return self._parse_patterns(raw, valid_ids={it["id"] for it in items})

    @staticmethod
    def _parse_patterns(raw: str, valid_ids: set) -> List[dict]:
        m = re.search(r"\[.*\]", raw, flags=re.S)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except ValueError:
            return []
        if not isinstance(data, list):
            return []
        out = []
        for entry in data:
            if not isinstance(entry, dict):
                continue
            try:
                kid = int(entry.get("id"))
            except (TypeError, ValueError):
                continue
            pattern = str(entry.get("pattern") or "").strip()
            if kid in valid_ids and pattern:
                out.append({"id": kid, "pattern": pattern})
        return out

    def match_patterns(self, patterns: List[dict]) -> List[dict]:
        """Find one pattern recurring in unrelated places — the analogy half.

        Only the labels are compared, never the underlying text, and the
        prompt's job is to reject the easy answer: consecutive scenes of one
        storyline share a pattern trivially and are exactly what the earlier
        version of this kept returning.
        """
        listing = "\n".join(
            "#{} [{}] {}".format(p["id"], p.get("where", ""), p["pattern"]) for p in patterns)
        prompt = (
            "下面是一批事件的抽象结构模式，方括号里是它出现的位置（章节/主要人物）。\n\n{}\n\n"
            "找出**同一个结构模式在互不相干的地方重复出现**的组。判断标准：\n"
            "- 结构要真的同构：动机的性质、因果的走向、谁得谁失的格局都对得上\n"
            "- 必须跨情境：同一段剧情的连续几幕、同一件事的前后步骤，**一律不算**，"
            "这是最容易犯的错，宁可少给也不要给这种\n"
            "- 涉及的人物不同、章节相隔较远的匹配才有价值\n\n"
            "每组至少 2 条，最多 6 组，找不到就输出 []。\n"
            '严格输出 JSON：[{{"item_ids":[...],"shared_logic":"这个重复出现的结构是什么，一句话"}}]'
        ).format(listing)
        raw = self.chat(prompt, max_tokens=1500, enable_thinking=False)
        return self._parse_logic_groups(raw, valid_ids={p["id"] for p in patterns})

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
