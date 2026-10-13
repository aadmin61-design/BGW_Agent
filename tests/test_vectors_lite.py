"""隔离验证Lite文件路径和索引选择，不连接真实向量库或调用模型。"""
from types import SimpleNamespace
from pymilvus import MilvusClient
from backend import vectors
from backend.config import Settings


class FakeClient:
    create_schema = staticmethod(MilvusClient.create_schema)

    def __init__(self, **kwargs):
        self.connection = kwargs

    def has_collection(self, name):
        return False

    def prepare_index_params(self):
        self.index = SimpleNamespace(add_index=lambda field, **kwargs: setattr(self, "index_options", kwargs))
        return self.index

    def create_collection(self, name, **kwargs):
        self.collection = name

    def load_collection(self, name):
        self.loaded = name


def test_lite_creates_parent_and_uses_flat_without_remote_token(tmp_path, monkeypatch):
    database = tmp_path / "data" / "knowledge.db"
    monkeypatch.setattr(vectors, "settings", lambda: SimpleNamespace(milvus_uri=str(database), milvus_token="remote-only-token", milvus_collection="bgw_knowledge_v1", embedding_dimensions=1024))
    monkeypatch.setattr(vectors, "MilvusClient", FakeClient)
    store = vectors.VectorStore()
    assert database.parent.is_dir()
    assert store.client.connection["uri"] == str(database.resolve())
    assert store.client.connection["token"] == ""
    assert store.client.index_options == {"index_type": "FLAT", "metric_type": "COSINE"}
    assert store.client.loaded == "bgw_knowledge_v1"


def test_network_milvus_remains_compatible(monkeypatch):
    monkeypatch.setattr(vectors, "settings", lambda: SimpleNamespace(milvus_uri="http://127.0.0.1:19530", milvus_token="local-token", milvus_collection="bgw_knowledge_v1", embedding_dimensions=1024))
    monkeypatch.setattr(vectors, "MilvusClient", FakeClient)
    store = vectors.VectorStore()
    assert store.client.connection["uri"] == "http://127.0.0.1:19530"
    assert store.client.connection["token"] == "local-token"
    assert store.client.index_options["index_type"] == "AUTOINDEX"


def test_lite_setting_uses_separate_name_and_preserves_legacy_alias():
    # 文件配置不占用SDK自动加载的MILVUS_URI，旧网络连接仍被识别。
    assert Settings(_env_file=None, VECTOR_URI="/opt/zhixu/data/knowledge.db").milvus_uri.endswith("knowledge.db")
    assert Settings(_env_file=None, MILVUS_URI="http://localhost:19530").milvus_uri == "http://localhost:19530"


def test_existing_lite_collection_is_explicitly_loaded(tmp_path, monkeypatch):
    monkeypatch.setattr(vectors, "settings", lambda: SimpleNamespace(milvus_uri=str(tmp_path / "existing.db"), milvus_token="", milvus_collection="bgw_knowledge_v1", embedding_dimensions=1024))
    monkeypatch.setattr(FakeClient, "has_collection", lambda self, name: True)
    monkeypatch.setattr(vectors, "MilvusClient", FakeClient)
    assert vectors.VectorStore().client.loaded == "bgw_knowledge_v1"


def test_integrity_detects_missing_and_wrong_vector_source():
    store = object.__new__(vectors.VectorStore)
    store.name = "bgw_knowledge_v1"
    chunks = [SimpleNamespace(id=str(i), kb_id="kb", text="正文", source="来源") for i in range(3)]
    store.client = SimpleNamespace(get=lambda *args, **kwargs: [
        {"id": "0", "kb_id": "kb", "text": "正文", "source": "来源"},
        {"id": "1", "kb_id": "kb", "text": "另一篇正文", "source": "来源"}])
    assert store.verify_chunks(chunks) == {"expected": 3, "missing": 1, "mismatched": 1, "ok": False}
