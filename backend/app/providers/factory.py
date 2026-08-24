"""Build providers from the environment on each call (no cached state).

This keeps tests able to monkeypatch QWEN_* / STT_* env vars per test case.
"""

from app.config import get_settings
from app.providers.base import LLMProvider, NoopLLMProvider, NoopSTTProvider, STTProvider
from app.providers.qwen import QwenProvider, QwenSTTProvider


def get_llm_provider() -> LLMProvider:
    settings = get_settings()
    if settings.llm_configured:
        return QwenProvider(
            base_url=settings.qwen_base_url,
            api_key=settings.qwen_api_key,
            model=settings.qwen_model,
            timeout=settings.llm_timeout,
        )
    return NoopLLMProvider()


def get_stt_provider() -> STTProvider:
    settings = get_settings()
    if settings.stt_configured:
        return QwenSTTProvider(
            base_url=settings.stt_base_url,
            api_key=settings.stt_api_key,
            model=settings.stt_model,
            timeout=settings.llm_timeout,
        )
    return NoopSTTProvider()
