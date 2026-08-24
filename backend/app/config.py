"""Environment-driven configuration.

Settings are re-read from the environment on every call (no module-level
singleton) so tests can monkeypatch environment variables and rebuild the app
per test without stale state.
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings:
    def __init__(self) -> None:
        env_dir = os.environ.get("KB_DATA_DIR", "").strip()
        self.data_dir = Path(env_dir) if env_dir else REPO_ROOT / "data"
        self.db_path = self.data_dir / "knowledge.db"
        self.uploads_dir = self.data_dir / "uploads"
        try:
            self.upload_max_bytes = int(os.environ.get("KB_UPLOAD_MAX_BYTES", "10485760"))
        except ValueError:
            self.upload_max_bytes = 10 * 1024 * 1024

        self.qwen_base_url = os.environ.get("QWEN_BASE_URL", "").strip().rstrip("/")
        self.qwen_api_key = os.environ.get("QWEN_API_KEY", "").strip()
        self.qwen_model = os.environ.get("QWEN_MODEL", "").strip()

        self.stt_base_url = os.environ.get("STT_BASE_URL", "").strip().rstrip("/")
        self.stt_api_key = os.environ.get("STT_API_KEY", "").strip()
        self.stt_model = os.environ.get("STT_MODEL", "").strip()

        try:
            self.llm_timeout = float(os.environ.get("KB_LLM_TIMEOUT", "30"))
        except ValueError:
            self.llm_timeout = 30.0

    @property
    def llm_configured(self) -> bool:
        return bool(self.qwen_base_url and self.qwen_model)

    @property
    def stt_configured(self) -> bool:
        return bool(self.stt_base_url and self.stt_model)


def get_settings() -> Settings:
    return Settings()
