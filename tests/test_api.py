from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from backend import main
from backend.database import get_db
from backend.models import Base, User, KnowledgeBase, ImportJob, Document, Chunk, Concept, Progress, DailyItem, Conversation, Message
from backend.security import passwords


@pytest.fixture
def api(monkeypatch):
    # 测试使用独立内存数据库，不连接用户MySQL、不调用云端模型。
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(main, "session_factory", lambda: factory)
    # 不启动定时线程；每个测试显式消费队列，避免误调用真实模型。
    async def no_scheduler(self):
        return
    monkeypatch.setattr(main.QuizService, "run", no_scheduler)
    main.app.dependency_overrides[get_db] = lambda: session_dependency(factory)
    # FastAPI依赖必须是generator函数，不能把generator对象当作结果。
    def dependency():
        with factory() as db:
            yield db
    main.app.dependency_overrides[get_db] = dependency
    main.attempts.clear()
    with factory() as db:
        admin = User(username="test_admin", password_hash=passwords.hash("test_password_12"), is_admin=True)
        a = User(username="alice", password_hash=passwords.hash("test_password_12"))
        b = User(username="bob", password_hash=passwords.hash("test_password_12"))
        db.add_all([admin, a, b]); db.flush()
        kb = KnowledgeBase(name="测试知识库", status="ready"); db.add(kb); db.flush()
        doc = Document(kb_id=kb.id, name="test.md", digest="a" * 64); db.add(doc); db.flush()
        chunk = Chunk(kb_id=kb.id, doc_id=doc.id, text="测试来源内容", source="test.md · 片段1"); db.add(chunk); db.flush()
        concepts = [Concept(kb_id=kb.id, chunk_id=chunk.id, title=f"概念{i}", category="基础", depth=1,
            question=f"问题{i}？", answer="答案", analysis="原理分析", prerequisites=[], prerequisite_titles=[]) for i in range(15)]
        db.add_all(concepts); db.commit()
        identifiers = SimpleNamespace(a=a.id, b=b.id, admin=admin.id, kb=kb.id, concepts=[c.id for c in concepts])
    with TestClient(main.app) as client:
        yield client, factory, identifiers
    main.app.dependency_overrides.clear()
    engine.dispose()


def session_dependency(factory):
    with factory() as db:
        yield db


def login(client, username="alice"):
    response = client.post("/api/auth/login", json={"username": username, "password": "test_password_12"})
    assert response.status_code == 200


def test_profile_is_private_and_cannot_change_credentials(api):
    client, factory, ids = api
    login(client)
    with factory() as db:
        original_hash = db.get(User, ids.a).password_hash
    response = client.patch('/api/profile', json={'display_name': '新的显示名字', 'bio': '喜欢学习Java'})
    assert response.status_code == 200
    assert response.json()['username'] == 'alice'
    assert response.json()['display_name'] == '新的显示名字'
    for protected in ['username', 'password', 'is_admin', 'user_id']:
        body = {'display_name': '不能修改账号', protected: 'anything'}
        assert client.patch('/api/profile', json=body).status_code == 422
    with factory() as db:
        assert db.get(User, ids.a).password_hash == original_hash
    login(client, 'bob')
    other = client.get('/api/auth/me').json()
    assert other['display_name'] == 'bob' and other['bio'] == ''
    assert client.get('/api/profile/avatar').status_code == 404
    login(client)
    assert client.get('/api/auth/me').json()['display_name'] == '新的显示名字'


def test_profile_avatar_validation_is_atomic_and_avatar_is_not_shared(api):
    import base64, struct, zlib
    from backend.profile import PNG, png_chunk
    client, factory, ids = api
    login(client)
    image = PNG + png_chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0)) + png_chunk(b'IDAT', zlib.compress(b'\0\x20\x80\x50\xff')) + png_chunk(b'IEND', b'')
    avatar = 'data:image/png;base64,' + base64.b64encode(image).decode()
    result = client.patch('/api/profile', json={'display_name': 'Alice', 'bio': '介绍', 'avatar_png': avatar})
    assert result.status_code == 200
    own_image = client.get(result.json()['avatar_url'])
    assert own_image.status_code == 200 and own_image.headers['content-type'] == 'image/png'
    assert client.patch('/api/profile', json={'display_name': '不应保存', 'avatar_png': 'bad'}).status_code == 422
    assert client.get('/api/auth/me').json()['display_name'] == 'Alice'
    login(client, 'bob')
    assert client.get(result.json()['avatar_url']).status_code == 404
    login(client)
    assert client.patch('/api/profile', json={'display_name': 'Alice', 'avatar_remove': True}).status_code == 200
    assert client.get('/api/profile/avatar').status_code == 404


def test_only_admin_can_publish_cached_prefix_and_running_job_cannot_repeat(api, monkeypatch):
    from backend.models import ImportCheckpoint
    client, factory, ids = api
    with factory() as db:
        job = ImportJob(kb_id=ids.kb, total=1, status="failed")
        db.add(job); db.flush()
        job_id = job.id
        db.add(ImportCheckpoint(kb_id=ids.kb, job_id=job_id, digest="b" * 64,
            name="long.docx", total_chunks=3, processed_chunks=2))
        db.commit()
    called = []
    monkeypatch.setattr(main, "run_publish_saved", lambda job_id: called.append(job_id))
    login(client)
    assert client.post(f"/api/admin/jobs/{job_id}/publish-saved").status_code == 403
    login(client, "test_admin")
    assert client.post(f"/api/admin/jobs/{job_id}/publish-saved").status_code == 202
    assert called == [job_id]
    assert client.post(f"/api/admin/jobs/{job_id}/publish-saved").status_code == 409


def create_lesson(client):
    response = client.post("/api/plans/lesson", json={})
    assert response.status_code == 200
    return response.json()["items"][0]


def test_registration_cannot_assign_admin_and_session_private(api):
    client, _, _ = api
    result = client.post("/api/auth/register", json={"username": "new_user", "password": "password123", "is_admin": True})
    assert result.status_code == 201 and result.json()["is_admin"] is False
    assert "password" not in str(result.json())
    assert client.post("/api/admin/knowledge-bases", json={"name": "forbidden"}).status_code == 403


def test_plan_idempotent_more_unique_and_user_isolation(api):
    client, _, _ = api; login(client)
    first = client.post("/api/plans/lesson", json={}).json()
    again = client.post("/api/plans/lesson", json={}).json()
    assert len(first["items"]) == 10 and first["items"] == again["items"]
    more = client.post("/api/plans/lesson", json={"more": True}).json()
    assert len(more["items"]) == 15 and len({i["id"] for i in more["items"]}) == 15
    item = first["items"][0]["id"]
    login(client, "bob")
    assert client.get(f"/api/items/{item}/conversation").status_code == 404
    assert client.post(f"/api/items/{item}/answer", json={}).status_code == 404
    assert client.post(f"/api/items/{item}/save", json={}).status_code == 404
    assert client.get("/api/plans/lesson").json() == []


def test_quiz_first_day_gate_then_exact_counts_and_no_answer_leak(api, monkeypatch):
    client, factory, ids = api; login(client)
    item = create_lesson(client)
    client.post(f"/api/items/{item['id']}/answer", json={"remembered": True})
    assert client.post("/api/plans/quiz", json={}).status_code == 409
    with factory() as db:
        p = db.scalar(select(Progress).where(Progress.user_id == ids.a))
        p.first_learned = main.today() - timedelta(days=1); db.commit()
    monkeypatch.setattr(main, "generate_quiz", lambda c, kind, variant: {"question": "选择题" if kind == "choice" else "填____", "options": ["甲", "乙", "丙", "丁"] if kind == "choice" else [], "answer": "B" if kind == "choice" else "答案", "accepted_answers": [], "analysis": "解析"})
    response = client.post("/api/plans/quiz", json={})
    assert response.status_code == 202 and response.json()["job"]["status"] == "queued"
    service = main.app.state.quiz_service
    ticket = service.claim_next()
    service.run_job(*ticket)
    items = client.get("/api/plans/quiz").json()
    assert len(items) == 13 and sum(i["kind"] == "choice" for i in items) == 10
    assert all("answer" not in i["snapshot"] and "analysis" not in i["snapshot"] for i in items)
    assert "answer" not in client.get(f"/api/items/{items[0]['id']}/conversation").json()["snapshot"]
    choice = items[0]
    correct_letter = "ABCD"[choice["snapshot"]["options"].index("乙")]
    # 旧页面的提交不能更新成绩，新位置对应的正确内容才被判定正确。
    assert client.post(f"/api/items/{choice['id']}/answer", json={"answer": "B"}).status_code == 409
    submitted = client.post(f"/api/items/{choice['id']}/answer", json={"answer": correct_letter,
        "option_order_version": choice["snapshot"]["option_order_version"]}).json()
    assert submitted["correct"] and submitted["snapshot"]["answer"] == correct_letter


def test_wrong_answer_reschedule_and_repeat_submit_idempotent(api):
    client, factory, ids = api; login(client)
    item = create_lesson(client)
    for _ in range(2):
        assert client.post(f"/api/items/{item['id']}/answer", json={"remembered": False}).status_code == 200
    with factory() as db:
        p = db.scalar(select(Progress).where(Progress.user_id == ids.a))
        assert p.mistakes == 1 and p.next_review == main.today() + timedelta(days=1)


def test_knowledge_integrity_is_admin_only_and_waits_for_completion(api, monkeypatch):
    from backend import vectors
    client, factory, ids = api
    monkeypatch.setattr(vectors, "vector_store", lambda: SimpleNamespace(verify_chunks=lambda rows:
        {"expected": len(rows), "missing": 0, "mismatched": 0, "ok": True}))
    login(client)
    assert client.get(f"/api/admin/knowledge-bases/{ids.kb}/integrity").status_code == 403
    login(client, "test_admin")
    response = client.get(f"/api/admin/knowledge-bases/{ids.kb}/integrity")
    assert response.status_code == 200 and response.json()["vectors"]["expected"] == 1
    assert "text" not in response.json() and response.json()["concepts"] == 15
    with factory() as db:
        db.get(KnowledgeBase, ids.kb).status = "indexing"; db.commit()
    assert client.get(f"/api/admin/knowledge-bases/{ids.kb}/integrity").status_code == 409


def test_generation_status_is_private_and_duplicate_clicks_reuse_job(api, monkeypatch):
    client, factory, ids = api; login(client)
    item = create_lesson(client)
    client.post(f"/api/items/{item['id']}/answer", json={})
    with factory() as db:
        db.scalar(select(Progress).where(Progress.user_id == ids.a)).first_learned -= timedelta(days=1)
        db.commit()
    response = client.post("/api/plans/quiz", json={})
    job = response.json()["job"]
    assert response.status_code == 202
    assert client.post("/api/plans/quiz", json={"more": True}).json()["job"]["id"] == job["id"]
    status = client.get("/api/plans/quiz/generation").json()
    assert status["timezone"] == "Asia/Shanghai" and status["job"]["id"] == job["id"]
    assert "user_id" not in status["job"] and "run_id" not in status["job"]
    login(client, "bob")
    assert client.get("/api/plans/quiz/generation").json()["job"] is None
    assert client.post("/api/plans/quiz", json={}).status_code == 409


def test_saved_conversations_survive_next_day_and_unsaved_expire(api):
    client, factory, _ = api; login(client)
    items = client.post("/api/plans/lesson", json={}).json()["items"]
    one, two = items[0]["id"], items[1]["id"]
    client.get(f"/api/items/{one}/conversation"); client.get(f"/api/items/{two}/conversation")
    client.post(f"/api/items/{one}/save", json={"saved": True})
    with factory() as db:
        for c in db.scalars(select(Conversation)):
            c.day -= timedelta(days=1)
            db.get(DailyItem, c.item_id).day -= timedelta(days=1)
        db.commit()
    assert client.get(f"/api/items/{one}/conversation").status_code == 200
    assert client.get(f"/api/items/{two}/conversation").status_code == 410
    assert len(client.get("/api/bookmarks").json()) == 1


def test_chat_contexts_scoped_and_model_failure_no_partial_message(api, monkeypatch):
    client, factory, ids = api; login(client)
    items = client.post("/api/plans/lesson", json={}).json()["items"]
    calls = []
    def invoke(context):
        calls.append(context)
        return {"reply": "模型测试回答", "context": [{"source": "test.md", "text": "来源"}]}
    monkeypatch.setattr(main, "tutor_graph", lambda: SimpleNamespace(invoke=invoke))
    for item in items[:2]:
        response = client.post(f"/api/items/{item['id']}/conversation", json={"message": "问题"})
        assert response.status_code == 200 and len(response.json()["messages"]) == 2
    assert all(c["history"] == [] and c["kb_id"] == ids.kb for c in calls)
    assert calls[0]["snapshot"]["question"] != calls[1]["snapshot"]["question"]
    def fail(context):
        raise RuntimeError("secret-provider-error")
    monkeypatch.setattr(main, "tutor_graph", lambda: SimpleNamespace(invoke=fail))
    response = client.post(f"/api/items/{items[0]['id']}/conversation", json={"message": "失败重试"})
    assert response.status_code == 503 and "secret" not in response.text
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Message)) == 4


@pytest.mark.parametrize("stage,expected", [("retrieval", "知识库检索暂不可用"), ("model", "助教模型暂时无法响应")])
def test_tutor_failure_names_service_and_rolls_back_question(api, monkeypatch, stage, expected):
    from backend import ai, vectors
    client, factory, _ = api; login(client)
    item = create_lesson(client)
    ai.tutor_graph.cache_clear()
    def fail(*args):
        raise RuntimeError("secret-connection-or-provider-detail")
    monkeypatch.setattr(vectors, "vector_store", lambda: SimpleNamespace(search=fail if stage == "retrieval" else lambda *args: []))
    monkeypatch.setattr(ai, "llm", lambda: SimpleNamespace(invoke=fail))
    response = client.post(f"/api/items/{item['id']}/conversation", json={"message": "测试问题"})
    assert response.status_code == 503 and expected in response.json()["detail"]
    assert "secret" not in response.text
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Message)) == 0
    ai.tutor_graph.cache_clear()


def test_same_second_chat_keeps_turn_order_in_history_and_bookmarks(api, monkeypatch):
    from datetime import datetime
    client, factory, _ = api
    login(client)
    item = create_lesson(client)
    # 强制同秒保存，并让回答UUID排在问题之前，复现真实MySQL中的旧排序问题。
    ids = iter(["f" * 32, "0" * 32, "e" * 32, "1" * 32, "d" * 32, "2" * 32])
    monkeypatch.setattr(Message.__table__.c.id.default, "arg", lambda context: next(ids))
    monkeypatch.setattr(Message.__table__.c.created_at.default, "arg", lambda context: datetime(2026, 10, 12, 9))
    histories = []
    def invoke(context):
        histories.append(context["history"])
        return {"reply": "回答" + str(len(histories)), "context": []}
    monkeypatch.setattr(main, "tutor_graph", lambda: SimpleNamespace(invoke=invoke))
    for i in range(3):
        result = client.post(f"/api/items/{item['id']}/conversation", json={"message": f"提问{i + 1}"})
        assert result.status_code == 200
        messages = result.json()["messages"]
        assert [m["role"] for m in messages] == ["user", "assistant"] * (i + 1)
        assert [m["ordinal"] for m in messages] == list(range(2 * (i + 1)))
    assert [m["content"] for m in histories[-1]] == ["提问1", "回答1", "提问2", "回答2"]
    client.post(f"/api/items/{item['id']}/save", json={"saved": True})
    messages = client.get("/api/bookmarks").json()[0]["messages"]
    assert [m["content"] for m in messages] == ["提问1", "回答1", "提问2", "回答2", "提问3", "回答3"]


def test_admin_delete_cascades_but_preserves_bookmark_snapshot(api, monkeypatch):
    client, factory, ids = api; login(client)
    item = create_lesson(client)
    client.post(f"/api/items/{item['id']}/save", json={"saved": True})
    login(client, "test_admin")
    from backend import vectors
    deleted = []
    monkeypatch.setattr(vectors, "vector_store", lambda: SimpleNamespace(delete_kb=deleted.append))
    assert client.delete(f"/api/admin/knowledge-bases/{ids.kb}").status_code == 200
    assert deleted == [ids.kb]
    login(client)
    saved = client.get("/api/bookmarks").json()
    assert len(saved) == 1 and saved[0]["snapshot"]["answer"] == "答案"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Concept)) == 0
        assert db.get(DailyItem, item["id"]).kb_id is None


def test_csrf_origin_rejected(api):
    client, _, _ = api; login(client)
    assert client.post("/api/plans/lesson", json={}, headers={"origin": "https://evil.example"}).status_code == 403


def test_dependencies_block_out_of_order_completion(api):
    client, factory, ids = api
    with factory() as db:
        db.get(Concept, ids.concepts[1]).prerequisites = [ids.concepts[0]]; db.commit()
    login(client)
    items = client.post("/api/plans/lesson", json={}).json()["items"]
    with factory() as db:
        dependent = db.scalar(select(DailyItem).where(DailyItem.concept_id == ids.concepts[1]))
        assert client.post(f"/api/items/{dependent.id}/answer", json={}).status_code == 409


def test_import_restart_reuses_sources_and_rejects_duplicate_or_active_delete(api, tmp_path, monkeypatch):
    client, factory, ids = api
    source = tmp_path / "retry.md"; source.write_text("测试知识", encoding="utf-8")
    monkeypatch.setattr(main.settings(), "import_root", tmp_path)
    calls = []
    monkeypatch.setattr(main, "run_import", lambda *args: calls.append(args))
    with factory() as db:
        job = ImportJob(kb_id=ids.kb, status="failed", total=1, completed=1, chunks=2,
            source_paths=[str(source)], source_kind="local")
        db.add(job); db.commit(); job_id = job.id
    login(client)
    assert client.post(f"/api/admin/jobs/{job_id}/restart", json={}).status_code == 403
    assert client.delete(f"/api/admin/jobs/{job_id}").status_code == 403
    login(client, "test_admin")
    result = client.post(f"/api/admin/jobs/{job_id}/restart", json={})
    assert result.status_code == 202 and result.json()["job_id"] == job_id
    assert calls == [(job_id, [source.resolve()], False)]
    assert client.post(f"/api/admin/jobs/{job_id}/restart", json={}).status_code == 409
    assert client.delete(f"/api/admin/jobs/{job_id}").status_code == 409
    with factory() as db:
        job = db.get(ImportJob, job_id)
        assert job.status == "queued" and job.completed == 0 and job.chunks == 0
        assert db.get(KnowledgeBase, ids.kb).status == "indexing"


def test_legacy_import_restart_requires_explicit_sources(api, tmp_path, monkeypatch):
    client, factory, ids = api
    source = tmp_path / "original.md"; source.write_text("知识", encoding="utf-8")
    monkeypatch.setattr(main.settings(), "import_root", tmp_path)
    calls = []
    monkeypatch.setattr(main, "run_import", lambda *args: calls.append(args))
    with factory() as db:
        job = ImportJob(kb_id=ids.kb, status="failed", total=4)
        db.add(job); db.commit(); job_id = job.id
    login(client, "test_admin")
    result = client.post(f"/api/admin/jobs/{job_id}/restart", json={})
    assert result.status_code == 409 and "重新选择" in result.json()["detail"]
    assert calls == []
    result = client.post(f"/api/admin/jobs/{job_id}/restart", json={"path": str(source)})
    assert result.status_code == 202 and calls[0][1] == [source.resolve()]
    with factory() as db:
        assert db.get(ImportJob, job_id).source_kind == "local"


def test_import_restart_uploaded_files_and_delete_only_task_copies(api, tmp_path, monkeypatch):
    client, factory, ids = api
    monkeypatch.setattr(main.settings(), "upload_dir", tmp_path / "uploads")
    calls = []
    monkeypatch.setattr(main, "run_import", lambda *args: calls.append(args))
    login(client, "test_admin")
    response = client.post(f"/api/admin/knowledge-bases/{ids.kb}/upload", files=[("files", ("sample.md", b"knowledge", "text/markdown"))])
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    with factory() as db:
        job = db.get(ImportJob, job_id)
        copy = Path(job.source_paths[0]); assert copy.is_file() and job.source_kind == "upload"
        job.status = "failed"; db.get(KnowledgeBase, ids.kb).status = "ready"; db.commit()
    rows = client.get("/api/admin/jobs").json()
    assert rows[0]["has_sources"] and "source_paths" not in rows[0]
    assert client.post(f"/api/admin/jobs/{job_id}/restart", json={}).status_code == 202
    assert calls[-1] == (job_id, [copy], True)
    with factory() as db:
        db.get(ImportJob, job_id).status = "failed"
        db.get(KnowledgeBase, ids.kb).status = "ready"
        db.commit()
    response = client.post(f"/api/admin/jobs/{job_id}/upload-retry", files=[("files", ("new.md", b"same batch", "text/markdown"))])
    assert response.status_code == 202 and not copy.exists()
    with factory() as db:
        job = db.get(ImportJob, job_id); new_copy = Path(job.source_paths[0]); assert new_copy.is_file()
        job.status = "partial"; db.get(KnowledgeBase, ids.kb).status = "ready"; db.commit()
    assert client.delete(f"/api/admin/jobs/{job_id}").status_code == 200
    assert not new_copy.exists()
    with factory() as db:
        assert db.get(ImportJob, job_id) is None
        assert db.get(KnowledgeBase, ids.kb) is not None
        assert db.scalar(select(func.count()).select_from(Concept)) == 15


def test_import_retry_missing_or_unauthorized_file_does_not_start(api, tmp_path, monkeypatch):
    client, factory, ids = api
    root = tmp_path / "allowed"; root.mkdir()
    outside = tmp_path / "original.md"; outside.write_text("原始资料", encoding="utf-8")
    monkeypatch.setattr(main.settings(), "import_root", root)
    monkeypatch.setattr(main.settings(), "upload_dir", root / "uploads")
    calls = []
    monkeypatch.setattr(main, "run_import", lambda *args: calls.append(args))
    with factory() as db:
        job = ImportJob(kb_id=ids.kb, status="failed", total=1, source_paths=[str(outside)], source_kind="local")
        db.add(job); db.commit(); job_id = job.id
    login(client, "test_admin")
    assert client.post(f"/api/admin/jobs/{job_id}/restart", json={}).status_code == 409
    assert client.post(f"/api/admin/jobs/{job_id}/restart", json={"path": str(outside)}).status_code == 409
    with factory() as db:
        job = db.get(ImportJob, job_id); job.source_paths = [str(root / "missing.md")]; db.commit()
    assert client.post(f"/api/admin/jobs/{job_id}/restart", json={}).status_code == 409 and not calls
    with factory() as db:
        job = db.get(ImportJob, job_id); job.source_kind = "upload"; job.source_paths = [str(outside)]; db.commit()
    assert client.delete(f"/api/admin/jobs/{job_id}").status_code == 200
    assert outside.read_text(encoding="utf-8") == "原始资料"


def test_import_failure_retains_copy_then_retry_deduplicates(api, tmp_path, monkeypatch):
    from backend import ingestion
    from backend.ai import ExtractedConcept
    client, factory, ids = api
    root = tmp_path / "uploads"; root.mkdir()
    copy = root / "copy.md"; content = "Java重试知识测试。"; copy.write_text(content, encoding="utf-8")
    monkeypatch.setattr(main.settings(), "upload_dir", root)
    monkeypatch.setattr(ingestion, "session_factory", lambda: factory)
    monkeypatch.setattr(ingestion, "vector_store", lambda: SimpleNamespace(upsert=lambda chunks: None, delete_chunks=lambda ids: None))
    def fail(*args):
        raise RuntimeError("model unavailable")
    monkeypatch.setattr(ingestion, "extract_concepts", fail)
    with factory() as db:
        job = ImportJob(kb_id=ids.kb, total=1, source_kind="upload", source_paths=[str(copy)])
        db.add(job); db.commit(); job_id = job.id
    ingestion._run_import(job_id, [copy], cleanup=True)
    with factory() as db:
        assert db.get(ImportJob, job_id).status == "partial"
        assert db.scalar(select(func.count()).select_from(Document)) == 1
        job = db.get(ImportJob, job_id); job.completed = 0; job.chunks = 0; job.status = "queued"; db.commit()
    assert copy.is_file()
    monkeypatch.setattr(ingestion, "extract_concepts", lambda *args: [ExtractedConcept(title="重试知识", category="Java", depth=1, question="测试？", answer="答案", analysis="分析")])
    ingestion._run_import(job_id, [copy], cleanup=True)
    assert not copy.exists()
    local = tmp_path / "original.md"; local.write_text(content, encoding="utf-8")
    with factory() as db:
        assert db.get(ImportJob, job_id).status == "completed"
        assert db.scalar(select(func.count()).select_from(Document)) == 2
        second = ImportJob(kb_id=ids.kb, total=1, source_kind="local", source_paths=[str(local)])
        db.add(second); db.commit(); second_id = second.id
    monkeypatch.setattr(ingestion, "extract_concepts", fail)
    ingestion._run_import(second_id, [local])
    with factory() as db:
        assert db.get(ImportJob, second_id).status == "completed"
        assert db.scalar(select(func.count()).select_from(Document)) == 2
    assert local.is_file()
