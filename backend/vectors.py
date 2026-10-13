from functools import lru_cache
from pathlib import Path
from pymilvus import MilvusClient, DataType
from .config import settings
from .ai import embeddings


class VectorStore:
    def __init__(self):
        cfg = settings()
        self.name = cfg.milvus_collection
        if not self.name.startswith("bgw_"):
            raise ValueError("本项目向量集合必须以 bgw_ 开头，避免操作其他项目数据")
        # 文件路径启用 Lite；保留原有网络连接，迁移期间本机服务不受影响。
        lite = cfg.milvus_uri.endswith(".db") and "://" not in cfg.milvus_uri
        uri = cfg.milvus_uri
        if lite:
            path = Path(uri).expanduser().resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            uri = str(path)
        self.client = MilvusClient(uri=uri, token="" if lite else cfg.milvus_token, timeout=30)
        if not self.client.has_collection(self.name):
            schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
            schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=32)
            schema.add_field("kb_id", DataType.VARCHAR, max_length=32)
            schema.add_field("text", DataType.VARCHAR, max_length=16000)
            schema.add_field("source", DataType.VARCHAR, max_length=2000)
            schema.add_field("vector", DataType.FLOAT_VECTOR, dim=cfg.embedding_dimensions)
            index = self.client.prepare_index_params()
            # Lite 只支持 FLAT，小知识库无需独立的向量服务容器。
            index.add_index("vector", index_type="FLAT" if lite else "AUTOINDEX", metric_type="COSINE")
            self.client.create_collection(self.name, schema=schema, index_params=index, consistency_level="Strong")
        if lite:
            # 显式加载已有集合，尽早发现Lite缓存目录不可写等运行环境故障。
            self.client.load_collection(self.name)

    def upsert(self, chunks):
        vectors = embeddings().embed_documents([c.text for c in chunks])
        self.client.upsert(self.name, data=[dict(id=c.id, kb_id=c.kb_id, text=c.text, source=c.source, vector=v)
                                           for c, v in zip(chunks, vectors, strict=True)])

    def search(self, kb_id, query):
        self._validate_id(kb_id)
        hits = self.client.search(self.name, data=[embeddings().embed_query(query)],
            filter=f'kb_id == "{kb_id}"', limit=5, output_fields=["text", "source"],
            search_params={"metric_type": "COSINE", "params": {}})[0]
        return [{"text": h["entity"]["text"], "source": h["entity"]["source"]} for h in hits]

    def delete_kb(self, kb_id):
        self._validate_id(kb_id)
        self.client.delete(self.name, filter=f'kb_id == "{kb_id}"')

    def delete_chunks(self, ids):
        if ids:
            self.client.delete(self.name, ids=ids)

    @staticmethod
    def _validate_id(value):
        import re
        if not re.fullmatch(r"[a-f0-9]{32}", value):
            raise ValueError("无效知识库编号")


@lru_cache
def vector_store():
    return VectorStore()
