"""只迁移本项目的数据；保留原始ID、密码哈希、收藏和既有向量。"""
import argparse
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import Date, DateTime, func, select
from backend.config import settings, ROOT
from backend.database import session_factory
from backend.models import Base
from backend.vectors import vector_store


def serial(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if hasattr(value, "tolist"):
        return value.tolist()
    raise TypeError("不支持的迁移字段")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_tables(conn):
    # 单个事务保持用户记录、题目与对话的同一快照，不操作源数据库。
    return {table.name: [dict(row) for row in conn.execute(select(table)).mappings()]
            for table in Base.metadata.sorted_tables}


def restore_tables(conn, tables):
    # 禁止覆盖有数据的目标，源ID全部保留，按外键依赖顺序恢复。
    if set(tables) != set(Base.metadata.tables):
        raise ValueError("迁移表清单不匹配")
    for table in Base.metadata.sorted_tables:
        if conn.scalar(select(func.count()).select_from(table)):
            raise ValueError("目标数据库已有数据，拒绝覆盖")
    for table in Base.metadata.sorted_tables:
        rows = []
        for raw in tables[table.name]:
            row = dict(raw)
            for column in table.columns:
                value = row.get(column.name)
                if isinstance(value, str) and isinstance(column.type, DateTime):
                    row[column.name] = datetime.fromisoformat(value)
                elif isinstance(value, str) and isinstance(column.type, Date):
                    row[column.name] = date.fromisoformat(value)
            rows.append(row)
        for start in range(0, len(rows), 100):
            conn.execute(table.insert(), rows[start:start + 100])


def export_snapshot(folder):
    folder = folder.resolve()
    if folder.exists():
        raise ValueError("迁移目录已存在，请使用新的目录，避免覆盖备份")
    folder.mkdir(parents=True)
    engine = session_factory().kw["bind"]
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn:
        with conn.begin():
            tables = read_tables(conn)
            if any(j["status"] in {"queued", "running"} for j in tables["import_jobs"]):
                raise ValueError("有导入任务正在运行，请完成后再迁移")
            if any(j["status"] in {"queued", "running"} for j in tables["quiz_generations"]):
                raise ValueError("有测验生成正在运行，请完成后再迁移")
            store = vector_store()
            vectors = []
            chunks = tables["chunks"]
            for start in range(0, len(chunks), 100):
                ids = [row["id"] for row in chunks[start:start + 100]]
                found = store.client.get(store.name, ids=ids,
                    output_fields=["id", "kb_id", "text", "source", "vector"])
                if {r["id"] for r in found} != set(ids):
                    raise ValueError("向量与知识片段不一致，停止迁移")
                vectors.extend(found)
    files = {}
    cfg = settings()
    # 只携带任务引用的本项目原始资料，不复制整个F盘或无关项目。
    roots = {"upload": cfg.upload_dir.resolve(), "local": cfg.import_root.resolve()}
    target_roots = {"upload": "/opt/zhixu/uploads", "local": "/opt/zhixu/imports"}
    # 旧任务没有路径清单，仍保留本项目已有上传资料，供管理员手动重试。
    if roots["upload"].exists():
        for path in roots["upload"].rglob("*"):
            if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(roots["upload"]):
                destination = folder / "uploads" / path.relative_to(roots["upload"])
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
                files[destination.relative_to(folder).as_posix()] = digest(destination)
    for job in tables["import_jobs"]:
        kind = job.get("source_kind")
        paths = job.get("source_paths") or []
        if kind not in roots or not paths:
            continue
        translated = []
        for raw in paths:
            path = Path(raw).resolve()
            if not path.is_relative_to(roots[kind]) or not path.is_file():
                translated = []
                break
            relative = path.relative_to(roots[kind])
            destination = folder / ("uploads" if kind == "upload" else "imports") / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
            files[destination.relative_to(folder).as_posix()] = digest(destination)
            translated.append(str(Path(target_roots[kind]) / relative).replace("\\", "/"))
        job["source_paths"] = translated or None
    payload = {"version": 1, "embedding_dimensions": cfg.embedding_dimensions,
               "embedding_model": cfg.embedding_model, "tables": tables, "vectors": vectors}
    path = folder / "snapshot.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, default=serial), encoding="utf-8")
    files["snapshot.json"] = digest(path)
    manifest = {"version": 1, "counts": {name: len(rows) for name, rows in tables.items()},
                "vectors": len(vectors), "files": files}
    (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"exported": manifest["counts"], "vectors": len(vectors)}, ensure_ascii=False))


def load_snapshot(folder):
    folder = folder.resolve()
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    for relative, expected in manifest["files"].items():
        path = (folder / relative).resolve()
        if not path.is_relative_to(folder) or digest(path) != expected:
            raise ValueError("迁移文件校验失败")
    payload = json.loads((folder / "snapshot.json").read_text(encoding="utf-8"))
    cfg = settings()
    if payload["version"] != 1 or payload["embedding_dimensions"] != cfg.embedding_dimensions or payload["embedding_model"] != cfg.embedding_model:
        raise ValueError("迁移版本或嵌入模型不一致")
    expected_ids = {row["id"] for row in payload["tables"]["chunks"]}
    if {row["id"] for row in payload["vectors"]} != expected_ids or len(expected_ids) != len(payload["vectors"]):
        raise ValueError("向量清单不完整")
    if any(len(row["vector"]) != cfg.embedding_dimensions for row in payload["vectors"]):
        raise ValueError("向量维度不匹配")
    return payload, manifest


def restore_snapshot(folder):
    payload, manifest = load_snapshot(folder)
    engine = session_factory().kw["bind"]
    Base.metadata.create_all(engine)
    store = vector_store()
    if int(store.client.get_collection_stats(store.name)["row_count"]) != 0:
        raise ValueError("目标向量集合已有数据，拒绝覆盖")
    # SQL整批事务；向量恢复失败时补偿本批ID，已有目标数据绝不清空。
    ids = [row["id"] for row in payload["vectors"]]
    written = False
    try:
        with engine.begin() as conn:
            restore_tables(conn, payload["tables"])
            written = True
            for start in range(0, len(ids), 100):
                store.client.upsert(store.name, data=payload["vectors"][start:start + 100])
            for start in range(0, len(ids), 100):
                found = store.client.get(store.name, ids=ids[start:start + 100], output_fields=["id"])
                if {r["id"] for r in found} != set(ids[start:start + 100]):
                    raise ValueError("恢复后的向量数量不一致")
    except Exception:
        if written and ids:
            store.client.delete(store.name, ids=ids)
        raise
    for directory, target in (("uploads", settings().upload_dir), ("imports", settings().import_root)):
        if (folder / directory).exists():
            shutil.copytree(folder / directory, target, dirs_exist_ok=True)
    store.client.close()
    print(json.dumps({"restored": manifest["counts"], "vectors": len(ids)}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["export", "restore", "verify"])
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "export":
            export_snapshot(args.folder)
        elif args.command == "restore":
            restore_snapshot(args.folder)
        else:
            _, manifest = load_snapshot(args.folder)
            print(json.dumps({"verified": manifest["counts"], "vectors": manifest["vectors"]}, ensure_ascii=False))
    except Exception:
        # 包含用户密码哈希与对话内容的迁移数据不能进入终端异常日志。
        print("迁移失败，目标不会覆盖已有数据；请检查任务状态、文件校验与服务连接。", file=sys.stderr)
        sys.exit(1)
