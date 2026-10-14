"""自动测试与本机实际配置隔离，不调用真实模型或依赖生产凭据。"""
import pytest
from backend.config import settings


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    monkeypatch.setenv("MYSQL_USER", "isolated_test")
    monkeypatch.setenv("MYSQL_PASSWORD", "")
    monkeypatch.setenv("JWT_SECRET", "isolated-test-signing-key-with-no-production-use")
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("VECTOR_URI", "http://milvus.test.invalid:19530")
    monkeypatch.setenv("MILVUS_TOKEN", "")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    settings.cache_clear()
    yield
    settings.cache_clear()
