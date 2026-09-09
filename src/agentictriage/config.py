from __future__ import annotations

import os
from dataclasses import dataclass

from agentictriage.providers import OpenAICompatibleProvider, lm_studio_provider


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str | None = None
    lmstudio_base_url: str = "http://127.0.0.1:1234/v1"
    lmstudio_model: str = "local-model"
    lmstudio_timeout_seconds: float = 20.0
    cors_origins: tuple[str, ...] = ("http://localhost:3080", "http://localhost:3004")

    @classmethod
    def from_environment(cls) -> Settings:
        return cls(
            database_url=os.getenv("TRIAGE_DATABASE_URL"),
            lmstudio_base_url=os.getenv("TRIAGE_LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1"),
            lmstudio_model=os.getenv("TRIAGE_LMSTUDIO_MODEL", "local-model"),
            lmstudio_timeout_seconds=float(os.getenv("TRIAGE_LMSTUDIO_TIMEOUT_SECONDS", "20")),
            cors_origins=tuple(
                origin.strip()
                for origin in os.getenv(
                    "TRIAGE_CORS_ORIGINS",
                    "http://localhost:3080,http://127.0.0.1:3080,"
                    "http://localhost:3004,http://127.0.0.1:3004",
                ).split(",")
                if origin.strip()
            ),
        )

    def providers(self) -> list[OpenAICompatibleProvider]:
        return [
            lm_studio_provider(
                base_url=self.lmstudio_base_url,
                model=self.lmstudio_model,
                timeout_seconds=self.lmstudio_timeout_seconds,
            )
        ]
