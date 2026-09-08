"""Embeddings via any OpenAI-compatible /embeddings endpoint (llama.cpp's
llama-server with --embeddings, in this deployment).

Kept deliberately dumb: one text in, one vector out, None on any failure. The
semantic layer is an enhancement over signature matching, never a dependency of
it, so nothing here is allowed to raise into a caller that is trying to save a
knowledge item.
"""

import json
from typing import List, Optional

import httpx

from app.providers.base import EmbeddingProvider


class OpenAICompatEmbeddingProvider(EmbeddingProvider):
    name = "openai-compat"

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 30.0):
        if not base_url or not model:
            raise ValueError("embedding provider requires base_url and model")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer {}".format(self.api_key)
        return headers

    def embed(self, text: str) -> Optional[List[float]]:
        text = (text or "").strip()
        if not text:
            return None
        url = "{}/embeddings".format(self.base_url)
        payload = {"model": self.model, "input": text}
        try:
            resp = httpx.post(url, json=payload, headers=self._headers(), timeout=self.timeout)
        except httpx.HTTPError:
            return None
        if resp.status_code != 200:
            return None
        try:
            data = resp.json()
            vector = data["data"][0]["embedding"]
        except (ValueError, KeyError, IndexError, TypeError):
            return None
        if not isinstance(vector, list) or not vector:
            return None
        # llama.cpp can return a nested [[...]] for pooled embeddings.
        if isinstance(vector[0], list):
            vector = vector[0]
        try:
            return [float(x) for x in vector]
        except (TypeError, ValueError):
            return None


def pack_vector(vector: List[float]) -> bytes:
    return json.dumps([round(float(x), 6) for x in vector]).encode("utf-8")


def unpack_vector(blob) -> List[float]:
    if blob is None:
        return []
    if isinstance(blob, bytes):
        blob = blob.decode("utf-8")
    try:
        return [float(x) for x in json.loads(blob)]
    except (ValueError, TypeError):
        return []


def cosine(a: List[float], b: List[float]) -> float:
    """Plain-Python cosine. At a few hundred lessons x 1024 dims this is tens of
    milliseconds, which is why no vector index (and no numpy) is needed here."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / ((na ** 0.5) * (nb ** 0.5))
