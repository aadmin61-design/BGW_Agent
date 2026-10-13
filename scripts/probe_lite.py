"""在独立 SQLite 快照上验证 Lite 搜索，不占用在线服务的向量文件。"""
import json
from contextlib import chdir
from pathlib import Path
import sqlite3
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.config import settings
from pymilvus import MilvusClient


def probe():
    cfg = settings()
    # SQLite 在线备份取得一致快照，诊断进程只打开自己创建的临时数据库。
    with tempfile.TemporaryDirectory(dir=cfg.upload_dir.parent / "data") as folder:
        path = Path(folder) / "probe.db"
        with sqlite3.connect(f"file:{cfg.milvus_uri}?mode=ro", uri=True) as source:
            with sqlite3.connect(path) as target:
                source.backup(target)
        # Lite会清理工作目录中的缓存，诊断必须使用自己的工作目录，避免影响在线缓存。
        with chdir(folder):
            client = MilvusClient(uri=str(path))
            try:
                rows = client.query(cfg.milvus_collection, filter="", limit=1,
                                    output_fields=["id", "kb_id", "vector"])
                assert rows, "快照没有向量"
                results = client.search(cfg.milvus_collection, data=[rows[0]["vector"]],
                    filter=f'kb_id == "{rows[0]["kb_id"]}"', limit=5,
                    output_fields=["text", "source"],
                    search_params={"metric_type": "COSINE", "params": {}})
                print(json.dumps({"search_hits": len(results[0]), "snapshot_search": "passed"}))
            finally:
                client.close()


if __name__ == "__main__":
    probe()
