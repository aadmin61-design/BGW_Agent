"""少量服务连通性验证，不全量导入、不输出密钥和供应商异常。"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from backend.database import session_factory
from backend.config import settings


def check():
    result = {}
    try:
        with session_factory()() as db:
            db.execute(text("SELECT 1"))
        result["mysql"] = "ok"
    except Exception:
        result["mysql"] = "unavailable"
    try:
        from pymilvus import MilvusClient
        cfg = settings()
        client = MilvusClient(uri=cfg.milvus_uri, token=cfg.milvus_token, timeout=10)
        client.list_collections()
        client.close()
        result["milvus"] = "ok"
    except Exception:
        result["milvus"] = "unavailable"
    try:
        from backend.ai import llm, embeddings
        llm().invoke("这是服务连通性检查，请只回答OK。")
        result["qwen_chat"] = "ok"
        vector = embeddings().embed_query("Java基础知识")
        result["qwen_embedding"] = "ok" if len(vector) == settings().embedding_dimensions else "dimension_mismatch"
        result["embedding_dimensions"] = len(vector)
    except Exception:
        result["qwen"] = "unavailable"
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    check()
