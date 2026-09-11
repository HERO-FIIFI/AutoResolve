from agentictriage.config import Settings


def test_blank_provider_timeouts_use_defaults(monkeypatch) -> None:
    monkeypatch.setenv("TRIAGE_LMSTUDIO_TIMEOUT_SECONDS", "")
    monkeypatch.setenv("TRIAGE_OLLAMA_TIMEOUT_SECONDS", "   ")

    settings = Settings.from_environment()

    assert settings.lmstudio_timeout_seconds == 20.0
    assert settings.ollama_timeout_seconds == 60.0


def test_provider_timeouts_accept_configured_values(monkeypatch) -> None:
    monkeypatch.setenv("TRIAGE_LMSTUDIO_TIMEOUT_SECONDS", "4.5")
    monkeypatch.setenv("TRIAGE_OLLAMA_TIMEOUT_SECONDS", "12")

    settings = Settings.from_environment()

    assert settings.lmstudio_timeout_seconds == 4.5
    assert settings.ollama_timeout_seconds == 12.0
