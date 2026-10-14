from datetime import datetime, timezone, date
from uuid import uuid4
from sqlalchemy import String, Text, JSON, Date, DateTime, Integer, Boolean, ForeignKey, UniqueConstraint, LargeBinary
from sqlalchemy.dialects.mysql import MEDIUMBLOB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def uid():
    return uuid4().hex


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class UserProfile(Base):
    # 资料与登录凭据独立存储，已有用户无需改写账号、密码或学习记录。
    __tablename__ = "user_profiles"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(40), default="")
    bio: Mapped[str] = mapped_column(String(500), default="")
    avatar: Mapped[bytes | None] = mapped_column(LargeBinary().with_variant(MEDIUMBLOB(), "mysql"), nullable=True)
    avatar_digest: Mapped[str] = mapped_column(String(64), default="")


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(24), default="empty")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ImportJob(Base):
    __tablename__ = "import_jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    kb_id: Mapped[str] = mapped_column(ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="queued")
    total: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[int] = mapped_column(Integer, default=0)
    chunks: Mapped[int] = mapped_column(Integer, default=0)
    # 保存服务器端文件清单，重启复用同一批资料；旧任务由管理员重新选择。
    source_paths: Mapped[list | None] = mapped_column(JSON, nullable=True, default=list)
    source_kind: Mapped[str | None] = mapped_column(String(16), nullable=True, default="legacy")
    message: Mapped[str] = mapped_column(Text, default="等待处理")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("kb_id", "digest"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    kb_id: Mapped[str] = mapped_column(ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    digest: Mapped[str] = mapped_column(String(64))


class ImportCheckpoint(Base):
    __tablename__ = "import_checkpoints"
    __table_args__ = (UniqueConstraint("kb_id", "digest"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    kb_id: Mapped[str] = mapped_column(ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("import_jobs.id", ondelete="SET NULL"), nullable=True, index=True)
    digest: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    parser_version: Mapped[int] = mapped_column(Integer, default=2)
    total_chunks: Mapped[int] = mapped_column(Integer)
    processed_chunks: Mapped[int] = mapped_column(Integer, default=0)
    vectorized_chunks: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ImportPiece(Base):
    __tablename__ = "import_pieces"
    checkpoint_id: Mapped[str] = mapped_column(ForeignKey("import_checkpoints.id", ondelete="CASCADE"), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 预留稳定的向量ID，缓存尚未成为正式知识点，不向学习计划暴露。
    chunk_id: Mapped[str] = mapped_column(String(32), default=uid)
    text: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(500))
    concepts: Mapped[list] = mapped_column(JSON, default=list)


class Chunk(Base):
    __tablename__ = "chunks"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    kb_id: Mapped[str] = mapped_column(ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True)
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(500))


class Concept(Base):
    __tablename__ = "concepts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    kb_id: Mapped[str] = mapped_column(ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True)
    chunk_id: Mapped[str] = mapped_column(ForeignKey("chunks.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(180))
    category: Mapped[str] = mapped_column(String(100))
    depth: Mapped[int] = mapped_column(Integer)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    analysis: Mapped[str] = mapped_column(Text)
    # 记录模型提出的名称，以及校验后形成的有向无环前置关系。
    prerequisite_titles: Mapped[list] = mapped_column(JSON, default=list)
    prerequisites: Mapped[list] = mapped_column(JSON, default=list)


class Progress(Base):
    __tablename__ = "progress"
    __table_args__ = (UniqueConstraint("user_id", "concept_id"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    concept_id: Mapped[str] = mapped_column(ForeignKey("concepts.id", ondelete="CASCADE"))
    first_learned: Mapped[date] = mapped_column(Date)
    last_reviewed: Mapped[date] = mapped_column(Date)
    next_review: Mapped[date] = mapped_column(Date, index=True)
    stage: Mapped[int] = mapped_column(Integer, default=0)
    mistakes: Mapped[int] = mapped_column(Integer, default=0)


class DailyItem(Base):
    __tablename__ = "daily_items"
    __table_args__ = (UniqueConstraint("user_id", "day", "kind", "ordinal"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kb_id: Mapped[str | None] = mapped_column(ForeignKey("knowledge_bases.id", ondelete="SET NULL"))
    concept_id: Mapped[str | None] = mapped_column(ForeignKey("concepts.id", ondelete="SET NULL"))
    day: Mapped[date] = mapped_column(Date, index=True)
    kind: Mapped[str] = mapped_column(String(20))
    ordinal: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    is_review: Mapped[bool] = mapped_column(Boolean, default=False)
    submitted: Mapped[bool] = mapped_column(Boolean, default=False)
    correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    user_answer: Mapped[str | None] = mapped_column(Text, nullable=True)


class QuizGeneration(Base):
    __tablename__ = "quiz_generations"
    __table_args__ = (UniqueConstraint("user_id", "day"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    source: Mapped[str] = mapped_column(String(16), default="manual")
    more: Mapped[bool] = mapped_column(Boolean, default=False)
    base_count: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=13)
    completed: Mapped[int] = mapped_column(Integer, default=0)
    # 每次运行使用独立令牌，超时或重试后旧线程不能写入新任务。
    run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    message: Mapped[str] = mapped_column(String(255), default="等待生成")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("user_id", "item_id"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("daily_items.id", ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(Date)
    saved: Mapped[bool] = mapped_column(Boolean, default=False)
    # 即使管理员删除知识库，收藏仍保留题目与答案快照。
    snapshot: Mapped[dict] = mapped_column(JSON)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("conversation_id", "ordinal", name="uq_messages_conversation_ordinal"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    # 使用显式序号保存问答顺序，不依赖秒级时间戳或随机UUID。
    ordinal: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    sources: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
