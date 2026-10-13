"""迁移测试只使用内存数据库，校验外键、日期、密码哈希和覆盖保护。"""
import json
from datetime import date, datetime
import pytest
from sqlalchemy import create_engine, event, select
from backend.models import Base, User, KnowledgeBase, Document, Chunk, Concept, DailyItem, Conversation, Message, Progress
from scripts.cloud_migrate import read_tables, restore_tables, serial


def database():
    engine = create_engine("sqlite://")
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    return engine


def test_roundtrip_preserves_identity_history_and_json():
    source, target = database(), database()
    with source.begin() as conn:
        conn.execute(User.__table__.insert(), dict(id="u" * 32, username="test", password_hash="original-hash", is_admin=True, created_at=datetime(2026, 10, 13)))
        conn.execute(KnowledgeBase.__table__.insert(), dict(id="k" * 32, name="知识库", description="", status="ready", created_at=datetime(2026, 10, 13)))
        conn.execute(Document.__table__.insert(), dict(id="d" * 32, kb_id="k" * 32, name="知识.md", digest="a" * 64))
        conn.execute(Chunk.__table__.insert(), dict(id="c" * 32, kb_id="k" * 32, doc_id="d" * 32, text="原文", source="知识.md"))
        conn.execute(Concept.__table__.insert(), dict(id="n" * 32, kb_id="k" * 32, chunk_id="c" * 32, title="知识", category="基础", depth=1, question="问题", answer="答案", analysis="分析", prerequisites=[], prerequisite_titles=[]))
        conn.execute(DailyItem.__table__.insert(), dict(id="i" * 32, user_id="u" * 32, kb_id="k" * 32, concept_id="n" * 32, day=date(2026, 10, 12), kind="lesson", ordinal=0, snapshot={"question": "问题", "answer": "答案"}, is_review=False, submitted=True, correct=True))
        conn.execute(Progress.__table__.insert(), dict(id="p" * 32, user_id="u" * 32, concept_id="n" * 32, first_learned=date(2026, 10, 12), last_reviewed=date(2026, 10, 12), next_review=date(2026, 10, 14), stage=1, mistakes=2))
        conn.execute(Conversation.__table__.insert(), dict(id="v" * 32, user_id="u" * 32, item_id="i" * 32, day=date(2026, 10, 12), saved=True, snapshot={"question": "问题"}))
        conn.execute(Message.__table__.insert(), [dict(id="m" * 32, conversation_id="v" * 32, ordinal=0, role="user", content="解释一下", sources=[], created_at=datetime(2026, 10, 12)), dict(id="a" * 32, conversation_id="v" * 32, ordinal=1, role="assistant", content="原来的回答", sources=[{"source": "知识.md"}], created_at=datetime(2026, 10, 12))])
        snapshot = json.loads(json.dumps(read_tables(conn), default=serial))
    with target.begin() as conn:
        restore_tables(conn, snapshot)
        assert conn.execute(select(User.__table__)).mappings().one()["password_hash"] == "original-hash"
        assert conn.execute(select(Conversation.__table__)).mappings().one()["saved"]
        assert conn.execute(select(Progress.__table__)).mappings().one()["next_review"] == date(2026, 10, 14)
        messages = list(conn.execute(select(Message.__table__).order_by(Message.ordinal)).mappings())
        assert [row["role"] for row in messages] == ["user", "assistant"]
        assert messages[1]["sources"] == [{"source": "知识.md"}]
        assert json.loads(json.dumps(read_tables(conn), default=serial)) == snapshot
    with target.begin() as conn:
        with pytest.raises(ValueError, match="拒绝覆盖"):
            restore_tables(conn, snapshot)
        assert conn.scalar(select(User.username)) == "test"
    source.dispose(); target.dispose()


def test_schema_mismatch_refuses_partial_restore():
    engine = database()
    with engine.begin() as conn:
        with pytest.raises(ValueError, match="清单不匹配"):
            restore_tables(conn, {"users": []})
    engine.dispose()
