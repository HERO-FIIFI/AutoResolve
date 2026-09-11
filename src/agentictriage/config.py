from __future__ import annotations

import os
from dataclasses import dataclass

from .providers import OpenAICompatibleProvider, lm_studio_provider, ollama_provider


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str | None = None
    lmstudio_base_url: str = "http://127.0.0.1:1234/v1"
    lmstudio_model: str = "local-model"
    lmstudio_timeout_seconds: float = 20.0
    ollama_base_url: str = "http://127.0.0.1:11434/v1"
    ollama_model: str = "qwen2.5:7b"
    ollama_timeout_seconds: float = 60.0
    auth_secret: str | None = None
    admin_username: str = "admin"
    admin_tenant_id: str = "example"
    admin_password: str | None = None
    cors_origins: tuple[str, ...] = ("http://localhost:3080", "http://localhost:3004")

    @classmethod
    def from_environment(cls) -> Settings:
        return cls(
            database_url=os.getenv("TRIAGE_DATABASE_URL"),
            lmstudio_base_url=os.getenv("TRIAGE_LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1"),
            lmstudio_model=os.getenv("TRIAGE_LMSTUDIO_MODEL", "local-model"),
            lmstudio_timeout_seconds=float(os.getenv("TRIAGE_LMSTUDIO_TIMEOUT_SECONDS", "20")),
            ollama_base_url=os.getenv("TRIAGE_OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"),
            ollama_model=os.getenv("TRIAGE_OLLAMA_MODEL", "qwen2.5:7b"),
            ollama_timeout_seconds=float(os.getenv("TRIAGE_OLLAMA_TIMEOUT_SECONDS", "60")),
            auth_secret=os.getenv("TRIAGE_AUTH_SECRET"),
            admin_username=os.getenv("TRIAGE_ADMIN_USERNAME", "admin"),
            admin_tenant_id=os.getenv("TRIAGE_ADMIN_TENANT_ID", "example"),
            admin_password=os.getenv("TRIAGE_ADMIN_PASSWORD"),
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
            ollama_provider(
                base_url=self.ollama_base_url,
                model=self.ollama_model,
                timeout_seconds=self.ollama_timeout_seconds,
            ),
            lm_studio_provider(
                base_url=self.lmstudio_base_url,
                model=self.lmstudio_model,
                timeout_seconds=self.lmstudio_timeout_seconds,
            ),
        ]
