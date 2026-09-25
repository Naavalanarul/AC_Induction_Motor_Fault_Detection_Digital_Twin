import pytest

from app.config import Settings, get_settings


def test_csv_env_values_are_parsed(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://a.example, http://b.example")
    monkeypatch.setenv("FEATURE_FLAGS", "x,y")
    s = Settings()
    assert s.cors_origins == ["http://a.example", "http://b.example"]
    assert s.feature_flags == {"x", "y"}


def test_production_requires_explicit_secret_and_no_cors_wildcard(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        get_settings()
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    monkeypatch.setenv("CORS_ORIGINS", "*")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="CORS"):
        get_settings()
    get_settings.cache_clear()
