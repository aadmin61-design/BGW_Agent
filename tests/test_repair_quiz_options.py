import json
from sqlalchemy import create_engine, select, func, event
from sqlalchemy.orm import sessionmaker
from backend.models import Base, User, DailyItem, Conversation, Message
from scripts import repair_quiz_options as repair


def test_repair_preserves_submissions_saved_chats_and_is_idempotent(tmp_path, monkeypatch):
    engine = create_engine("sqlite://")
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    cfg = repair.settings().model_copy(update={"upload_dir": tmp_path / "uploads"})
    monkeypatch.setattr(repair, "settings", lambda: cfg)
    monkeypatch.setattr(repair, "session_factory", lambda: factory)
    day = repair.datetime.now(repair.ZoneInfo(cfg.app_timezone)).date()
    with factory() as db:
        user = User(username="repair_test", password_hash="unused")
        db.add(user); db.flush()
        snapshot = {"question": "Java题目", "options": ["正确", "错一", "错二", "错三"],
                    "answer": "A", "analysis": "A正确，B、C、D错误。"}
        rows = [DailyItem(user_id=user.id, day=day, kind="choice", ordinal=i,
                    snapshot=dict(snapshot), submitted=i == 0, user_answer="A" if i == 0 else None,
                    correct=True if i == 0 else None) for i in range(6)]
        db.add_all(rows); db.flush()
        saved = Conversation(user_id=user.id, item_id=rows[1].id, day=day, saved=True, snapshot=dict(snapshot))
        chat = Conversation(user_id=user.id, item_id=rows[2].id, day=day, snapshot=dict(snapshot))
        db.add_all([saved, chat]); db.flush()
        db.add(Message(conversation_id=chat.id, ordinal=0, role="user", content="为什么A正确？"))
        db.commit()
        ids = [row.id for row in rows]
    repair.repair(apply=False)
    with factory() as db:
        assert all("option_order_version" not in db.get(DailyItem, identifier).snapshot for identifier in ids)
    repair.repair(apply=True)
    with factory() as db:
        for identifier in ids[:3]:
            assert db.get(DailyItem, identifier).snapshot == snapshot
        assert db.get(DailyItem, ids[0]).user_answer == "A" and db.get(DailyItem, ids[0]).correct
        fixed = [db.get(DailyItem, identifier).snapshot for identifier in ids[3:]]
        assert all(quiz["options"]["ABCD".index(quiz["answer"])] == "正确" for quiz in fixed)
        assert db.scalar(select(func.count()).select_from(Message)) == 1
    backups = list((tmp_path / "data" / "maintenance").glob("*.json"))
    assert len(backups) == 1 and len(json.loads(backups[0].read_text(encoding="utf-8"))) == 3
    repair.repair(apply=True)
    assert len(list((tmp_path / "data" / "maintenance").glob("*.json"))) == 1
    with factory() as db:
        assert [db.get(DailyItem, identifier).snapshot for identifier in ids[3:]] == fixed
    engine.dispose()
