"""测试配置与真实服务器凭据隔离，无需项目私有.env。"""
import pytest
from backend.config import settings


@pytest.fixture(autouse=True)
def isolated_test_settings(monkeypatch):
    # API测试另行注入内存数据库；这里只保证初始化门槛不依赖个人MySQL配置。
    monkeypatch.setenv("MYSQL_USER", "isolated_test")
    monkeypatch.setenv("MYSQL_PASSWORD", "")
    monkeypatch.setenv("JWT_SECRET", "isolated-test-signing-key-with-no-production-use")
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("VECTOR_URI", "http://milvus.test.invalid:19530")
    monkeypatch.setenv("MILVUS_TOKEN", "")
    settings.cache_clear()
    yield
    settings.cache_clear()
