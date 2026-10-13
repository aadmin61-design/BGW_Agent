"""真实HTTP小规模验收，只使用已有管理员和节选知识，不全量导入。"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx

ROOT = Path(__file__).resolve().parents[1]


def smoke():
    secret = (ROOT / "data" / "admin-credentials.txt").read_text(encoding="utf-8").splitlines()
    username, password = [line.split(": ", 1)[1] for line in secret[:2]]
    with httpx.Client(base_url="http://127.0.0.1:8001", timeout=150) as client:
        results = {}
        for route in ("/", "/assets/app.js", "/assets/styles.css", "/assets/demo.js", "/api/health"):
            results[route] = client.get(route).status_code
        response = client.post("/api/auth/login", json={"username": username, "password": password})
        results["admin_login"] = response.status_code
        if response.status_code != 200:
            raise RuntimeError("管理员登录失败")
        bases = client.get("/api/knowledge-bases").json()
        results["knowledge_bases"] = len(bases)
        response = client.post("/api/plans/lesson", json={})
        results["lesson_plan_status"] = response.status_code
        items = response.json().get("items", [])
        results["lesson_count"] = len(items)
        if items:
            question = items[0]["id"]
            # 问答走真实LangGraph、Milvus检索与阿里云，只验证一题。
            answer = client.post(f"/api/items/{question}/conversation", json={"message": "请用一句话解释本题的关键点，并引用资料来源。"})
            results["tutor_status"] = answer.status_code
            if answer.status_code == 200:
                convo = answer.json()
                results["tutor_messages"] = len(convo["messages"])
                results["source_count"] = len(convo["messages"][-1]["sources"])
                results["bookmark_status"] = client.post(f"/api/items/{question}/save", json={"saved": True}).status_code
        print(json.dumps(results, ensure_ascii=False), flush=True)
        # 不展示管理员密码、cookie或模型全文。
        if results["lesson_count"] != 10 or results.get("tutor_status") != 200:
            sys.exit(1)


if __name__ == "__main__":
    try:
        smoke()
    except Exception:
        print("HTTP验证未完成，请检查服务状态；敏感信息未输出。", file=sys.stderr)
        sys.exit(1)
