"""Provider abstractions.

The system must work with no LLM/STT configured: Noop implementations give
honest fallbacks (truncated summary, empty tags, None transcript) and the API
layer reports which provider produced the result.
"""

import abc
from typing import List, Optional


class LLMProvider(abc.ABC):
    name: str = "base"

    @abc.abstractmethod
    def summarize(self, title: str, content: str) -> str:
        """Return a short summary for one knowledge item."""

    @abc.abstractmethod
    def suggest_tags(self, title: str, content: str) -> List[str]:
        """Return 0-5 suggested tags."""

    def find_logic_groups(self, items: List[dict], context: Optional[str] = None) -> List[dict]:
        """Group items sharing an underlying cause/mechanism, not just a topic.

        Concrete (not abstract) with an empty default: this is an optional
        enhancement layered on top of the core provider contract, not
        something every provider must implement — a provider that only ever
        gets asked to summarize is still a complete provider.
        """
        return []

    def is_configured(self) -> bool:
        return True


class NoopLLMProvider(LLMProvider):
    """Fallback used when QWEN_* env is absent: never raises, never pretends."""

    name = "noop"

    def summarize(self, title: str, content: str) -> str:
        text = (content or "").strip() or title.strip()
        text = " ".join(text.split())
        return text[:120] + ("…" if len(text) > 120 else "")

    def suggest_tags(self, title: str, content: str) -> List[str]:
        return []

    def is_configured(self) -> bool:
        return False


class EmbeddingProvider(abc.ABC):
    name: str = "base"
    dim: int = 0

    @abc.abstractmethod
    def embed(self, text: str) -> Optional[List[float]]:
        """Vector for one text, or None when it could not be produced.

        Returning None rather than raising keeps callers writable: a knowledge
        item must still save when the embedding service is down.
        """

    def is_configured(self) -> bool:
        return True


class NoopEmbeddingProvider(EmbeddingProvider):
    """Used when EMBED_* env is absent: the semantic layer simply isn't there,
    and lesson matching falls back to signature keys alone."""

    name = "noop"

    def embed(self, text: str) -> Optional[List[float]]:
        return None

    def is_configured(self) -> bool:
        return False


class RerankProvider(abc.ABC):
    name: str = "base"

    @abc.abstractmethod
    def rerank(self, query: str, documents: List[str]) -> Optional[List[float]]:
        """Relevance score per document, aligned with `documents`, or None when
        unavailable.

        A cross-encoder reads query and document together instead of comparing
        two independently-built vectors, which is why its scores separate far
        more sharply than cosine — measured here, ~3.0 of headroom around the
        cutoff versus ~0.1 for the bi-encoder.
        """

    def is_configured(self) -> bool:
        return True


class NoopRerankProvider(RerankProvider):
    """Used when RERANK_* env is absent: matching falls back to raw vector
    similarity with a tighter, more fragile floor."""

    name = "noop"

    def rerank(self, query: str, documents: List[str]) -> Optional[List[float]]:
        return None

    def is_configured(self) -> bool:
        return False


class STTProvider(abc.ABC):
    name: str = "base"

    @abc.abstractmethod
    def transcribe(self, audio_path: str, mime_type: str) -> Optional[str]:
        """Transcribe audio; return None when the provider has no result
        (callers must not invent a transcript)."""

    def is_configured(self) -> bool:
        return True


class NoopSTTProvider(STTProvider):
    name = "noop"

    def transcribe(self, audio_path: str, mime_type: str) -> Optional[str]:
        return None

    def is_configured(self) -> bool:
        return False
