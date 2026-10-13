"""服务器维护入口：通过在线管理员API提交导入，不另开进程操作Lite文件。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from sqlalchemy import select
from backend.database import session_factory
from backend.models import User
from backend.security import token


def submit(path, name):
    source = Path(path)
    with session_factory()() as db:
        administrator = db.scalar(select(User).where(User.is_admin.is_(True)))
        if administrator is None:
            raise RuntimeError("没有可用的管理员账号")
    # 会话只在服务器内存中使用，不输出密码、Cookie或JWT。
    with httpx.Client(base_url="http://127.0.0.1:8001", timeout=30, trust_env=False) as client:
        client.cookies.set("bgw_session", token(administrator))
        response = client.get("/api/knowledge-bases")
        response.raise_for_status()
        existing = next((kb for kb in response.json() if kb["name"] == name), None)
        if existing:
            kb_id = existing["id"]
            jobs = client.get("/api/admin/jobs"); jobs.raise_for_status()
            active = next((job for job in jobs.json() if job["kb_id"] == kb_id and job["status"] in {"queued", "running"}), None)
            if active:
                return {"kb_id": kb_id, "job_id": active["id"], "already_running": True}
        else:
            response = client.post("/api/admin/knowledge-bases", json={"name": name,
                "description": "完整文档的正文、表格及可提取图形文字；由模型分类并构建学习知识点。"})
            response.raise_for_status()
            kb_id = response.json()["id"]
        response = client.post(f"/api/admin/knowledge-bases/{kb_id}/import-local", json={"path": str(source)})
        if response.status_code != 202:
            raise RuntimeError(f"提交导入返回HTTP {response.status_code}")
        report = {"kb_id": kb_id, "job_id": response.json()["job_id"],
                  "sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "status": "submitted"}
        return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(submit(args.path, args.name), ensure_ascii=False))
    except Exception as error:
        print(json.dumps({"status": "failed", "type": type(error).__name__}, ensure_ascii=False))
        sys.exit(1)
