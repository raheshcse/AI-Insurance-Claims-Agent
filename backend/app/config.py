"""Application configuration.

Values come from the environment (see .env.example at the project root).
Nothing here is a business threshold -- thresholds are governance policy and
will live in governance/policy.py from Phase 4, per the VSL spec's import rules.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings:
    def __init__(self) -> None:
        self.app_env: str = os.environ.get("APP_ENV", "development")
        self.log_level: str = os.environ.get("LOG_LEVEL", "INFO")

        self.backend_host: str = os.environ.get("BACKEND_HOST", "127.0.0.1")
        self.backend_port: int = int(os.environ.get("BACKEND_PORT", "8000"))

        raw_origins = os.environ.get(
            "CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
        )
        self.cors_allowed_origins: list[str] = [
            origin.strip() for origin in raw_origins.split(",") if origin.strip()
        ]

        self.claims_store_path: Path = Path(
            os.environ.get("CLAIMS_STORE_PATH", str(PROJECT_ROOT / "data" / "claims" / "claims.jsonl"))
        )
        self.analyses_store_path: Path = Path(
            os.environ.get(
                "ANALYSES_STORE_PATH",
                str(PROJECT_ROOT / "data" / "claims" / "analyses.jsonl"),
            )
        )
        self.review_queue_store_path: Path = Path(
            os.environ.get(
                "REVIEW_QUEUE_STORE_PATH",
                str(PROJECT_ROOT / "data" / "claims" / "review_queue.jsonl"),
            )
        )
        self.conversations_store_path: Path = Path(
            os.environ.get(
                "CONVERSATIONS_STORE_PATH",
                str(PROJECT_ROOT / "data" / "claims" / "conversations.jsonl"),
            )
        )
        self.synthetic_data_dir: Path = Path(
            os.environ.get("SYNTHETIC_DATA_DIR", str(PROJECT_ROOT / "data" / "synthetic"))
        )
        self.use_synthetic_data: bool = (
            os.environ.get("USE_SYNTHETIC_DATA", "true").lower() == "true"
        )

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
