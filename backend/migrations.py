"""为已有消息补充稳定序号；仅修改本项目messages表，不删除对话。"""
from itertools import groupby, zip_longest
from sqlalchemy import inspect, text


def migrate_import_sources(engine):
    # 只补充可空列，原有任务和知识数据保留，不猜测旧任务的原始路径。
    columns = {column["name"] for column in inspect(engine).get_columns("import_jobs")}
    with engine.begin() as conn:
        if "source_paths" not in columns:
            conn.execute(text("ALTER TABLE import_jobs ADD COLUMN source_paths JSON NULL"))
        if "source_kind" not in columns:
            conn.execute(text("ALTER TABLE import_jobs ADD COLUMN source_kind VARCHAR(16) NULL"))


def migrate_message_order(engine):
    columns = {c["name"]: c for c in inspect(engine).get_columns("messages")}
    if "ordinal" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE messages ADD COLUMN ordinal INTEGER NULL"))
    with engine.begin() as conn:
        conversations = conn.scalars(text("SELECT DISTINCT conversation_id FROM messages WHERE ordinal IS NULL")).all()
        for conversation_id in conversations:
            rows = conn.execute(text("SELECT id, role, created_at FROM messages WHERE conversation_id = :conversation_id "
                                     "ORDER BY created_at, id"), {"conversation_id": conversation_id}).all()
            ordered = []
            for _, group in groupby(rows, key=lambda row: row.created_at):
                same_second = list(group)
                users = [row for row in same_second if row.role == "user"]
                assistants = [row for row in same_second if row.role == "assistant"]
                # 旧版同秒UUID排序可能倒置；恢复先提问、后回答的交替顺序。
                for pair in zip_longest(users, assistants):
                    ordered.extend(row for row in pair if row is not None)
                ordered.extend(row for row in same_second if row.role not in {"user", "assistant"})
            for ordinal, row in enumerate(ordered):
                conn.execute(text("UPDATE messages SET ordinal = :ordinal WHERE id = :id"),
                             {"ordinal": ordinal, "id": row.id})
    inspector = inspect(engine)
    names = {index["name"] for index in inspector.get_indexes("messages")}
    names.update(constraint["name"] for constraint in inspector.get_unique_constraints("messages"))
    if "uq_messages_conversation_ordinal" not in names:
        with engine.begin() as conn:
            conn.execute(text("CREATE UNIQUE INDEX uq_messages_conversation_ordinal ON messages (conversation_id, ordinal)"))
    if engine.dialect.name == "mysql" and inspect(engine).get_columns("messages"):
        columns = {c["name"]: c for c in inspect(engine).get_columns("messages")}
        if columns["ordinal"]["nullable"]:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE messages MODIFY COLUMN ordinal INTEGER NOT NULL"))
