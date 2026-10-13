"""长文恢复使用隔离数据库和模型替身，不调用真实模型。"""
from types import SimpleNamespace
import pytest
from sqlalchemy import create_engine, event, select, func
from sqlalchemy.orm import sessionmaker
from backend import ingestion
from backend.ai import ExtractedConcept
from backend.models import Base, KnowledgeBase, ImportJob, ImportCheckpoint, ImportPiece, Document, Chunk, Concept


@pytest.fixture
def importer(tmp_path, monkeypatch):
    engine = create_engine("sqlite://")
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(ingestion, "session_factory", lambda: factory)
    path = tmp_path / "full.md"; path.write_text("甲乙丙", encoding="utf-8")
    pieces = [(text, f"full.md · 片段{i + 1}") for i, text in enumerate("甲乙丙")]
    monkeypatch.setattr(ingestion, "parse_document", lambda _: pieces)
    calls, deleted = [], []
    def extract(text, titles):
        calls.append(text)
        return [ExtractedConcept(title="概念" + text, category="Java", depth=1,
            question="问题" + text, answer="答案", analysis="有来源的分析")]
    monkeypatch.setattr(ingestion, "extract_concepts", extract)
    monkeypatch.setattr(ingestion, "vector_store", lambda: SimpleNamespace(upsert=lambda chunks: None,
        delete_chunks=lambda ids: deleted.extend(ids)))
    with factory() as db:
        kb = KnowledgeBase(name="完整版"); db.add(kb); db.flush()
        job = ImportJob(kb_id=kb.id, total=1); db.add(job); db.commit()
        ids = kb.id, job.id
    yield factory, path, ids, extract, calls, deleted
    engine.dispose()


def test_failed_chunk_resumes_without_repeating_saved_model_calls(importer, monkeypatch):
    factory, path, (kb_id, job_id), extract, calls, _ = importer
    def fail(text, titles):
        if text == "乙":
            raise RuntimeError("provider_secret_must_not_be_exposed")
        return extract(text, titles)
    monkeypatch.setattr(ingestion, "extract_concepts", fail)
    ingestion._run_import(job_id, [path])
    with factory() as db:
        job = db.get(ImportJob, job_id)
        assert job.status == "failed" and "知识提取" in job.message and "provider_secret" not in job.message
        assert db.scalar(select(func.count()).select_from(Document)) == 0
        assert db.scalar(select(func.count()).select_from(Concept)) == 0
        checkpoint = db.scalar(select(ImportCheckpoint))
        assert checkpoint.processed_chunks == 1 and not checkpoint.completed
        job.status, job.completed, job.chunks = "queued", 0, 0; db.commit()
    monkeypatch.setattr(ingestion, "extract_concepts", extract)
    ingestion._run_import(job_id, [path])
    with factory() as db:
        assert db.get(ImportJob, job_id).status == "completed"
        assert db.get(KnowledgeBase, kb_id).status == "ready"
        assert db.scalar(select(func.count()).select_from(Document)) == 1
        assert db.scalar(select(func.count()).select_from(Chunk)) == 3
        assert db.scalar(select(func.count()).select_from(Concept)) == 3
        assert db.scalar(select(func.count()).select_from(ImportPiece)) == 0
    assert calls.count("甲") == 1 and path.exists()


def test_vector_failure_keeps_extraction_cache_and_does_not_publish(importer, monkeypatch):
    factory, path, (_, job_id), _, calls, deleted = importer
    def unavailable(chunks):
        raise RuntimeError("vector_unavailable")
    monkeypatch.setattr(ingestion, "vector_store", lambda: SimpleNamespace(upsert=unavailable,
        delete_chunks=lambda ids: deleted.extend(ids)))
    ingestion._run_import(job_id, [path])
    with factory() as db:
        assert db.get(ImportJob, job_id).status == "failed"
        assert db.scalar(select(func.count()).select_from(Document)) == 0
        assert db.scalar(select(func.count()).select_from(Chunk)) == 0
        assert db.scalar(select(func.count()).select_from(ImportPiece)) == 3
        checkpoint = db.scalar(select(ImportCheckpoint))
        assert checkpoint.processed_chunks == 3 and checkpoint.vectorized_chunks == 0
        job = db.get(ImportJob, job_id); job.status, job.completed = "queued", 0; db.commit()
    assert len(deleted) == 3
    count = len(calls)
    monkeypatch.setattr(ingestion, "vector_store", lambda: SimpleNamespace(upsert=lambda chunks: None, delete_chunks=lambda _: None))
    ingestion._run_import(job_id, [path])
    assert len(calls) == count
    with factory() as db:
        assert db.get(ImportJob, job_id).status == "completed"
        assert db.scalar(select(func.count()).select_from(Document)) == 1
