"""生成服务器私密迁移包；不打包本机环境、工具或其他项目密码。"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import secrets
import shutil
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.config import ROOT, settings


def package(snapshot):
    cfg = settings()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = ROOT / "data" / f"server-package-{stamp}"
    target.mkdir(parents=True)
    for name in ("backend", "web", "frontend", "deploy/ubuntu-lite"):
        shutil.copytree(ROOT / name, target / name,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "reference-frames"))
    (target / "scripts").mkdir()
    for name in ("cloud_migrate.py", "manage.py", "verify_server.py", "probe_lite.py", "repair_quiz_options.py", "build-web.mjs", "build-web-vendor.mjs"):
        shutil.copy2(ROOT / "scripts" / name, target / "scripts" / name)
    shutil.copy2(ROOT / "requirements.lock.txt", target / "requirements.lock.txt")
    for name in ("package.json", "package-lock.json", "tailwind.config.js"):
        if (ROOT / name).exists():
            shutil.copy2(ROOT / name, target / name)
    shutil.copytree(snapshot, target / "migration")
    # 云端生成独立数据库凭证，模型参数沿用本机，不复制MySQL root密码。
    values = {"LLM_API_URL": cfg.llm_api_url, "LLM_API_KEY": cfg.llm_api_key,
              "TEXT_MODEL": cfg.text_model, "EMBEDDING_MODEL": cfg.embedding_model,
              "EMBEDDING_DIMENSIONS": str(cfg.embedding_dimensions),
              "VECTOR_URI": "/opt/zhixu/data/knowledge.db", "MILVUS_TOKEN": "",
              "MILVUS_COLLECTION": cfg.milvus_collection,
              "MYSQL_HOST": "127.0.0.1", "MYSQL_PORT": "3306", "MYSQL_USER": "bgw",
              "MYSQL_PASSWORD": secrets.token_urlsafe(32), "MYSQL_DATABASE": "bgw_agent",
              "JWT_SECRET": secrets.token_urlsafe(48), "COOKIE_SECURE": "false",
              "CORS_ORIGINS": json.dumps(["http://8.133.250.141"]),
              "IMPORT_ROOT": "/opt/zhixu/imports", "UPLOAD_DIR": "/opt/zhixu/uploads",
              "APP_TIMEZONE": "Asia/Shanghai", "MAX_FILE_MB": str(cfg.max_file_mb)}
    def quote(value):
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
    (target / ".env").write_text("\n".join(f"{key}={quote(value)}" for key, value in values.items()) + "\n", encoding="utf-8")
    archive = target.with_suffix(".tar.gz")
    with tarfile.open(archive, "w:gz") as tar:
        for path in sorted(target.rglob("*")):
            if path.is_file():
                tar.add(path, arcname=path.relative_to(target).as_posix(), recursive=False)
    # 日志只显示路径、文件大小和校验值，不显示实际凭证或用户内容。
    result = {"archive": str(archive), "bytes": archive.stat().st_size,
              "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
              "instance_id": "i-uf6e1rfne2p3y5kzwjuy", "region": "cn-shanghai",
              "public_ip": "8.133.250.141", "status": "prepared_not_uploaded"}
    (ROOT / "data" / "server-migration-status.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot", type=Path)
    package(parser.parse_args().snapshot.resolve())
