from sqlalchemy import create_engine, text
from backend.migrations import migrate_message_order


def test_legacy_same_second_messages_migrate_without_losing_history():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE messages (id TEXT PRIMARY KEY, conversation_id TEXT, role TEXT, content TEXT, created_at DATETIME)"))
        conn.execute(text("CREATE TABLE unrelated (content TEXT)"))
        conn.execute(text("INSERT INTO unrelated VALUES ('keep')"))
        conn.execute(text("INSERT INTO messages VALUES (:id, :convo, :role, :content, :created)"), [
            {"id": "z1", "convo": "one", "role": "user", "content": "第一问", "created": "2026-10-12 09:00:00"},
            {"id": "a1", "convo": "one", "role": "assistant", "content": "第一答", "created": "2026-10-12 09:00:00"},
            {"id": "z2", "convo": "one", "role": "user", "content": "第二问", "created": "2026-10-12 09:00:01"},
            {"id": "a2", "convo": "one", "role": "assistant", "content": "第二答", "created": "2026-10-12 09:00:01"},
            {"id": "z3", "convo": "two", "role": "user", "content": "独立问", "created": "2026-10-12 09:00:00"},
            {"id": "a3", "convo": "two", "role": "assistant", "content": "独立答", "created": "2026-10-12 09:00:00"},
        ])
    migrate_message_order(engine)
    migrate_message_order(engine)
    with engine.connect() as conn:
        messages = conn.execute(text("SELECT content, ordinal FROM messages WHERE conversation_id='one' ORDER BY ordinal")).all()
        assert messages == [("第一问", 0), ("第一答", 1), ("第二问", 2), ("第二答", 3)]
        assert conn.scalar(text("SELECT COUNT(*) FROM messages")) == 6
        assert conn.scalar(text("SELECT content FROM unrelated")) == "keep"
    engine.dispose()
