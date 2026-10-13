"""使用独立SQLite与假模型验证定时、队列、失败恢复，不调用阿里云。"""
from datetime import datetime, time, timedelta
import pytest
from sqlalchemy import create_engine, event, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from backend.models import Base, User, KnowledgeBase, Document, Chunk, Concept, Progress, DailyItem, QuizGeneration, utcnow
from backend import quiz_jobs


def fake_quiz(concept, kind, variant):
    return {"question": f"问题{variant}" if kind == "choice" else f"第{variant}题____",
        "options": ["甲", "乙", "丙", "丁"] if kind == "choice" else [],
        "answer": "B" if kind == "choice" else "答案", "analysis": "知识依据", "accepted_answers": []}


@pytest.fixture
def queue():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    day = quiz_jobs.local_now().date()
    with factory() as db:
        users = [User(username=name, password_hash="unused") for name in ["learned", "firstday", "new"]]
        db.add_all(users); db.flush()
        kb = KnowledgeBase(name="测试", status="ready"); db.add(kb); db.flush()
        doc = Document(kb_id=kb.id, name="test.md", digest="a"*64); db.add(doc); db.flush()
        chunk = Chunk(kb_id=kb.id, doc_id=doc.id, text="来源", source="test.md"); db.add(chunk); db.flush()
        c = Concept(kb_id=kb.id, chunk_id=chunk.id, title="知识", category="基础", depth=1,
            question="问", answer="答", analysis="原理", prerequisites=[], prerequisite_titles=[])
        db.add(c); db.flush()
        for i in range(2):
            db.add(Progress(user_id=users[i].id, concept_id=c.id, first_learned=day-timedelta(days=1-i),
                last_reviewed=day, next_review=day, stage=0, mistakes=0))
        db.commit()
        ids = [user.id for user in users]
    service = quiz_jobs.QuizService(factory, fake_quiz, day_fn=lambda: day)
    yield service, factory, ids, day
    engine.dispose()


def enqueue(service, factory, user_id, day, more=False):
    with factory() as db:
        _, job = service.enqueue(db, user_id, day, more=more)
        db.commit()
        return job.id


def test_beijing_six_am_and_once_per_eligible_user(queue):
    service, factory, ids, day = queue
    before = datetime.combine(day, time(5, 59, 59), tzinfo=quiz_jobs.QUIZ_ZONE)
    at_six = before + timedelta(seconds=1)
    assert service.enqueue_due(before) == 0
    # 用同一瞬间的UTC输入验证不依赖服务器本地时区。
    assert service.enqueue_due(at_six.astimezone(quiz_jobs.timezone.utc)) == 1
    assert service.enqueue_due(at_six + timedelta(hours=2)) == 0
    with factory() as db:
        job = db.scalar(select(QuizGeneration))
        assert job.user_id == ids[0] and job.source == "automatic"
        assert db.scalar(select(func.count()).select_from(QuizGeneration)) == 1
    assert quiz_jobs.next_generation(before).startswith(str(day) + "T06:00:00")
    assert quiz_jobs.next_generation(at_six).startswith(str(day + timedelta(days=1)) + "T06:00:00")


def test_manual_before_six_deduplicates_and_atomic_13_questions(queue):
    service, factory, ids, day = queue
    job_id = enqueue(service, factory, ids[0], day)
    assert enqueue(service, factory, ids[0], day, more=True) == job_id
    ticket = service.claim_next()
    assert service.claim_next() is None
    service.run_job(*ticket)
    with factory() as db:
        rows = quiz_jobs.quiz_rows(db, ids[0], day)
        assert len(rows) == 13 and sum(row.kind == "choice" for row in rows) == 10
        assert [row.ordinal for row in rows] == list(range(13))
        assert db.get(QuizGeneration, job_id).status == "completed"
        _, job = service.enqueue(db, ids[0], day)
        assert job is None
    enqueue(service, factory, ids[0], day, more=True)
    service.run_job(*service.claim_next())
    with factory() as db:
        assert len(quiz_jobs.quiz_rows(db, ids[0], day)) == 26


def test_failure_has_no_partial_quiz_and_manual_retry_succeeds(queue):
    service, factory, ids, day = queue
    def fail(c, kind, variant):
        if variant == 5:
            raise RuntimeError("secret-model-response")
        return fake_quiz(c, kind, variant)
    service.generate = fail
    job_id = enqueue(service, factory, ids[0], day)
    service.run_job(*service.claim_next())
    with factory() as db:
        job = db.get(QuizGeneration, job_id)
        assert job.status == "failed" and "secret" not in job.message
        assert quiz_jobs.quiz_rows(db, ids[0], day) == []
    assert service.enqueue_due(datetime.combine(day, time(8), tzinfo=quiz_jobs.QUIZ_ZONE)) == 0
    service.generate = fake_quiz
    enqueue(service, factory, ids[0], day)
    service.run_job(*service.claim_next())
    with factory() as db:
        assert len(quiz_jobs.quiz_rows(db, ids[0], day)) == 13


def test_expired_worker_cannot_overwrite_retry(queue):
    service, factory, ids, day = queue
    job_id = enqueue(service, factory, ids[0], day)
    old_ticket = service.claim_next()
    with factory() as db:
        db.get(QuizGeneration, job_id).expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    service.enqueue_due(datetime.combine(day, time(8), tzinfo=quiz_jobs.QUIZ_ZONE))
    enqueue(service, factory, ids[0], day)
    new_ticket = service.claim_next()
    service.run_job(*old_ticket)
    with factory() as db:
        assert db.get(QuizGeneration, job_id).run_id == new_ticket[1]
        assert quiz_jobs.quiz_rows(db, ids[0], day) == []
    service.run_job(*new_ticket)
    with factory() as db:
        assert len(quiz_jobs.quiz_rows(db, ids[0], day)) == 13


def test_total_timeout_ends_loading_without_partial_items(queue, monkeypatch):
    service, factory, ids, day = queue
    job_id = enqueue(service, factory, ids[0], day)
    def timeout(*args, **kwargs):
        raise quiz_jobs.FuturesTimeout()
    monkeypatch.setattr(quiz_jobs, "as_completed", timeout)
    service.run_job(*service.claim_next())
    with factory() as db:
        assert db.get(QuizGeneration, job_id).status == "failed"
        assert quiz_jobs.quiz_rows(db, ids[0], day) == []


def test_day_rollover_discards_old_generation(queue):
    service, factory, ids, day = queue
    job_id = enqueue(service, factory, ids[0], day)
    ticket = service.claim_next()
    service.day = lambda: day + timedelta(days=1)
    service.enqueue_due(datetime.combine(day+timedelta(days=1), time(5), tzinfo=quiz_jobs.QUIZ_ZONE))
    service.run_job(*ticket)
    with factory() as db:
        assert db.get(QuizGeneration, job_id).status == "failed"
        assert quiz_jobs.quiz_rows(db, ids[0], day) == []


def test_restart_after_six_catches_up_and_skips_existing_quiz(queue):
    service, factory, ids, day = queue
    assert service.enqueue_due(datetime.combine(day, time(10), tzinfo=quiz_jobs.QUIZ_ZONE)) == 1
    service.run_job(*service.claim_next())
    with factory() as db:
        db.delete(db.scalar(select(QuizGeneration)))
        db.commit()
    assert service.enqueue_due(datetime.combine(day, time(11), tzinfo=quiz_jobs.QUIZ_ZONE)) == 0
