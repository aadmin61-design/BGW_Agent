"""只读核对迁移数据与服务；登录探针不打印密码、Cookie或模型密钥。"""
import argparse
import json
import secrets
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from sqlalchemy import select, func
from backend.config import settings
from backend.database import session_factory
from backend.models import Base, User, KnowledgeBase, DailyItem


def verify(model=False, base_url="http://127.0.0.1:8001"):
    # 核对真实服务器库，不写题目、学习进度或收藏对话。
    factory = session_factory()
    with factory() as db:
        counts = {table.name: db.scalar(select(func.count()).select_from(table)) for table in Base.metadata.sorted_tables}
        users = list(db.scalars(select(User)))
        kb = db.scalar(select(KnowledgeBase).where(KnowledgeBase.status == "ready"))
    expected = json.loads(Path("migration/snapshot.json").read_text(encoding="utf-8"))
    expected_users = {row["id"]: (row["username"], row["password_hash"], row["is_admin"])
                      for row in expected["tables"]["users"]}
    # 迁移后允许正常注册新用户，仅核对原有账号未被改写或丢失。
    actual_users = {user.id: (user.username, user.password_hash, user.is_admin) for user in users}
    assert all(actual_users.get(key) == value for key, value in expected_users.items()), "original_accounts"
    report = {"counts": counts}
    report["original_accounts_and_password_hashes"] = "matched"
    with httpx.Client(base_url=base_url, timeout=15, trust_env=False) as client:
        response = client.get("/api/health")
        assert response.status_code == 200 and response.json()["database"]
        if settings().milvus_uri.endswith(".db"):
            assert response.json()["vector"] is True, "online_lite_load"
        assert client.get("/api/dashboard").status_code == 401
        report["health"] = "ready"
        # 密码仅在服务器内存生成，用临时账号验证注册、登录，随后精确清理。
        credentials = {"username": "deploy_probe_" + secrets.token_hex(6), "password": secrets.token_urlsafe(24)}
        probe_id = None
        try:
            response = client.post("/api/auth/register", json=credentials)
            assert response.status_code == 201
            probe_id = response.json()["id"]
            client.cookies.clear()
            response = client.post("/api/auth/login", json=credentials)
            assert response.status_code == 200 and client.cookies.get("bgw_session")
            assert client.get("/api/auth/me").status_code == 200
            assert client.get("/api/dashboard").status_code == 200
            report["registration_and_password_login"] = "passed"
            if model and kb:
                # 经真实HTTP接口验证在线进程的检索权限和模型，不能由另一个CLI进程代替。
                plans = client.post("/api/plans/lesson", json={})
                assert plans.status_code == 200 and plans.json()["items"]
                item_id = plans.json()["items"][0]["id"]
                question = {"message": "请用一句话解释这道题，引用知识库资料。"}
                conversation = client.post(f"/api/items/{item_id}/conversation", json=question, timeout=150)
                assert conversation.status_code == 200, f"tutor_http_{conversation.status_code}"
                messages = conversation.json()["messages"]
                assert [message["role"] for message in messages] == ["user", "assistant"]
                assert messages[-1]["content"].strip() and messages[-1]["sources"]
                report["tutor"] = {"http_status": 200, "sources": len(messages[-1]["sources"]),
                    "reply_characters": len(messages[-1]["content"])}
        finally:
            with factory() as db:
                # 即使断言失败也只清理本次生成的账号，不按前缀批量删除。
                probe = db.scalar(select(User).where(User.username == credentials["username"]))
                if probe and (probe_id is None or probe.id == probe_id):
                    db.delete(probe)
                    db.commit()
        # 对两名原有用户分别签发内存测试会话，检查所有返回题目均属于该用户。
        from backend.security import token
        for user in users:
            client.cookies.clear()
            client.cookies.set("bgw_session", token(user))
            response = client.get("/api/plans/lesson")
            assert response.status_code == 200
            with factory() as db:
                own_ids = set(db.scalars(select(DailyItem.id).where(DailyItem.user_id == user.id)))
            assert all(item["id"] in own_ids for item in response.json())
            if not user.is_admin:
                assert client.get("/api/admin/jobs").status_code == 403
            else:
                assert client.get("/api/admin/jobs").status_code == 200
        report["user_isolation"] = "passed"
    with factory() as db:
        assert db.scalar(select(User.id).where(User.username == credentials["username"])) is None
    report["temporary_probe_cleanup"] = "passed"
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    args = parser.parse_args()
    try:
        verify(args.model, args.base_url)
    except Exception as error:
        # 不展示供应商响应体或测试凭据；仅报告故障类型和已分类阶段。
        print(json.dumps({"verification": "failed", "type": type(error).__name__, "stage": getattr(error, "stage", None)}))
        sys.exit(1)
