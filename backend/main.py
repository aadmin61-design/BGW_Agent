from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from collections import defaultdict, deque
import hashlib
import asyncio
import time
from fastapi import FastAPI, Depends, HTTPException, Request, Response, UploadFile, File, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ConfigDict, field_validator
from sqlalchemy import select, func, delete, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from .config import settings, ROOT
from .database import get_db, session_factory
from .models import Base, User, KnowledgeBase, ImportJob, Document, Chunk, Concept, Progress, DailyItem, Conversation, Message, uid
from .security import passwords, token, current_user, admin_user
from .scheduler import choose_lessons, review_update, normalize_answer
from .ingestion import local_files, run_import, run_publish_saved, SUPPORTED, retry_files, cleanup_uploads
from .ai import generate_quiz, tutor_graph, TutorUnavailable
from .migrations import migrate_message_order, migrate_import_sources
from .quiz_jobs import QuizService, job_view, next_generation
from .models import QuizGeneration, ImportCheckpoint, UserProfile
from .profile import normalise_avatar


def today():
    return datetime.now(ZoneInfo(settings().app_timezone)).date()


def initialize():
    with session_factory()() as db:
        Base.metadata.create_all(db.get_bind())
        migrate_message_order(db.get_bind())
        migrate_import_sources(db.get_bind())
        # 单进程任务无法在重启后继续，明确标记中断，允许重新导入。
        for job in db.scalars(select(ImportJob).where(ImportJob.status.in_(["queued", "running"]))):
            if db.get_bind().dialect.name == "mysql" and db.scalar(
                text("SELECT IS_USED_LOCK(:name)"), {"name": "bgw_job_" + job.id}) is not None:
                continue
            job.status = "failed"
            job.message = "服务重启导致导入中断，重启任务可从已保存片段继续；完整文档自动去重。"
        db.commit()
        for kb in db.scalars(select(KnowledgeBase).where(KnowledgeBase.status == "indexing")):
            active = db.scalar(select(ImportJob.id).where(ImportJob.kb_id == kb.id, ImportJob.status.in_(["queued", "running"])))
            if active:
                continue
            kb.status = "ready" if db.scalar(select(Concept.id).where(Concept.kb_id == kb.id).limit(1)) else "empty"
        db.commit()


@asynccontextmanager
async def lifespan(app):
    # MySQL暂未配置时仍可打开网页；API明确报告未就绪，不冒充真实数据。
    app.state.database_ready = False
    app.state.quiz_service = None
    app.state.vector_ready = None
    lite_store = None
    quiz_task = None
    if settings().mysql_user:
        try:
            initialize()
            app.state.database_ready = True
            app.state.quiz_service = QuizService(session_factory(), lambda c, k, v: generate_quiz(c, k, v), day_fn=today)
            quiz_task = asyncio.create_task(app.state.quiz_service.run())
        except Exception:
            pass
    if app.state.database_ready and settings().milvus_uri.endswith(".db") and "://" not in settings().milvus_uri:
        # 在实际服务进程中预加载Lite，健康检查不能只通过另一个诊断进程验证。
        from .vectors import vector_store
        try:
            lite_store = await asyncio.to_thread(vector_store)
            app.state.vector_ready = True
        except Exception:
            app.state.vector_ready = False
    try:
        yield
    finally:
        if quiz_task:
            app.state.quiz_service.stop.set()
            await quiz_task
        if lite_store:
            await asyncio.to_thread(lite_store.client.close)
            vector_store.cache_clear()


app = FastAPI(title="知序 · 知识学习助手", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings().cors_origins,
                   allow_credentials=True, allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type"])
attempts = defaultdict(deque)


@app.middleware("http")
async def guards(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            # HttpOnly会话配合严格Origin检查防跨站写请求。
            origin = request.headers.get("origin")
            allowed = settings().cors_origins + [str(request.base_url).rstrip("/")]
            if origin and origin not in allowed:
                return JSONResponse({"detail": "请求来源不受信任"}, status_code=403)
        if request.url.path in {"/api/auth/login", "/api/auth/register"}:
            ip = request.client.host if request.client else "unknown"
            bucket = attempts[ip]
            now = time.monotonic()
            while bucket and bucket[0] < now - 60:
                bucket.popleft()
            if len(bucket) >= 20:
                return JSONResponse({"detail": "请求过于频繁，请一分钟后重试"}, status_code=429)
            bucket.append(now)
        if request.url.path != "/api/health" and not app.state.database_ready:
            return JSONResponse({"detail": "数据库尚未就绪，请配置MySQL并重启服务"}, status_code=503)
    try:
        response = await call_next(request)
    except Exception:
        # 在供应商/数据库异常到达ASGI日志前转换，避免连接信息进入异常日志。
        response = JSONResponse({"detail": "服务处理失败，请检查数据库、模型及向量服务后重试"}, status_code=503)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(Exception)
async def unexpected(request, exc):
    # 不将数据库密码、供应商响应体或本地路径输出到网页。
    return JSONResponse({"detail": "服务处理失败，请检查数据库、模型及向量服务后重试"}, status_code=503)


class AuthInput(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[\w\-\u4e00-\u9fff]+$")
    password: str = Field(min_length=8, max_length=128)


class KBInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)


class PathInput(BaseModel):
    path: str = Field(max_length=1000)


class PlanInput(BaseModel):
    more: bool = False


class ImportRetryInput(BaseModel):
    path: str | None = Field(default=None, max_length=1000)


class AnswerInput(BaseModel):
    answer: str = Field(default="", max_length=2000)
    remembered: bool = True
    option_order_version: int | None = None


class ChatInput(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class SaveInput(BaseModel):
    saved: bool = True


class ProfileInput(BaseModel):
    # 明确拒绝账号、密码、用户ID和管理权限等额外字段。
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=1, max_length=40)
    bio: str = Field(default="", max_length=500)
    avatar_png: str | None = Field(default=None, max_length=350000)
    avatar_remove: bool = False

    @field_validator("display_name")
    @classmethod
    def nonempty_name(cls, value):
        if not value.strip():
            raise ValueError("名字不能为空")
        return value.strip()


def user_view(user, db=None):
    profile = db.get(UserProfile, user.id) if db is not None else None
    return {"id": user.id, "username": user.username, "is_admin": user.is_admin,
            "display_name": profile.display_name if profile and profile.display_name else user.username,
            "bio": profile.bio if profile else "",
            "avatar_url": f"/api/profile/avatar?v={profile.avatar_digest}" if profile and profile.avatar else None}


def login_cookie(response, user):
    response.set_cookie("bgw_session", token(user), httponly=True, secure=settings().cookie_secure,
                        samesite="strict", max_age=7 * 86400, path="/")


@app.get("/api/health")
def health():
    vector_ready = getattr(app.state, "vector_ready", None)
    status = "configuration_required" if not app.state.database_ready else "degraded" if vector_ready is False else "ready"
    return {"status": status, "database": app.state.database_ready,
            "model_configured": bool(settings().llm_api_key), "vector": vector_ready}


@app.post("/api/auth/register", status_code=201)
def register(body: AuthInput, response: Response, db: Session = Depends(get_db)):
    user = User(username=body.username.strip(), password_hash=passwords.hash(body.password))
    db.add(user)
    try:
        db.flush()
        login_cookie(response, user)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "用户名已存在")
    return user_view(user, db)


@app.post("/api/auth/login")
def login(body: AuthInput, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username.strip()))
    # 不存在的账号也做一次Argon2校验，减小用户名枚举的时间差。
    stored = user.password_hash if user else passwords.hash("unavailable-account")
    if not passwords.verify(body.password, stored) or not user:
        raise HTTPException(401, "用户名或密码错误")
    login_cookie(response, user)
    return user_view(user, db)


@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie("bgw_session", path="/")
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return user_view(user, db)


@app.patch("/api/profile")
def update_profile(body: ProfileInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.avatar_remove and body.avatar_png is not None:
        raise HTTPException(422, "不能同时上传和移除头像")
    try:
        avatar = normalise_avatar(body.avatar_png) if body.avatar_png is not None else None
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    # 同一用户从两个标签页首次保存时按用户行串行化，防止重复插入资料。
    db.execute(select(User.id).where(User.id == user.id).with_for_update())
    profile = db.get(UserProfile, user.id)
    if profile is None:
        profile = UserProfile(user_id=user.id)
        db.add(profile)
    # 所有图片校验通过后一次提交；永远只修改当前登录用户的资料。
    profile.display_name, profile.bio = body.display_name, body.bio.strip()
    if avatar is not None or body.avatar_remove:
        profile.avatar = avatar
        profile.avatar_digest = hashlib.sha256(avatar).hexdigest() if avatar else ""
    db.commit()
    return user_view(user, db)


@app.get("/api/profile/avatar")
def profile_avatar(user: User = Depends(current_user), db: Session = Depends(get_db)):
    profile = db.get(UserProfile, user.id)
    if profile is None or not profile.avatar:
        raise HTTPException(404, "尚未设置头像")
    return Response(content=profile.avatar, media_type="image/png")


@app.get("/api/knowledge-bases")
def knowledge_bases(user: User = Depends(current_user), db: Session = Depends(get_db)):
    result = []
    for kb in db.scalars(select(KnowledgeBase).order_by(KnowledgeBase.created_at)):
        result.append({"id": kb.id, "name": kb.name, "description": kb.description, "status": kb.status,
            "documents": db.scalar(select(func.count()).select_from(Document).where(Document.kb_id == kb.id)),
            "concepts": db.scalar(select(func.count()).select_from(Concept).where(Concept.kb_id == kb.id))})
    return result


@app.post("/api/admin/knowledge-bases", status_code=201)
def create_kb(body: KBInput, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    kb = KnowledgeBase(name=body.name, description=body.description)
    db.add(kb)
    db.commit()
    return {"id": kb.id, "name": kb.name}


@app.get("/api/admin/knowledge-bases/{kb_id}/integrity")
def knowledge_integrity(kb_id: str, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    kb = db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(404, "知识库不存在")
    if kb.status != "ready":
        raise HTTPException(409, "知识库尚未处理完成")
    from .vectors import vector_store
    chunks = list(db.scalars(select(Chunk).where(Chunk.kb_id == kb_id)))
    result = vector_store().verify_chunks(chunks)
    # 仅返回统计，不通过诊断接口下发原文、向量或凭据。
    return {"kb_id": kb.id, "documents": db.scalar(select(func.count()).select_from(Document).where(Document.kb_id == kb.id)),
            "concepts": db.scalar(select(func.count()).select_from(Concept).where(Concept.kb_id == kb.id)), "vectors": result}


def lock_kb(db, kb_id):
    kb = db.scalar(select(KnowledgeBase).where(KnowledgeBase.id == kb_id).with_for_update())
    if not kb:
        raise HTTPException(404, "知识库不存在")
    if kb.status in {"indexing", "deleting"}:
        raise HTTPException(409, "知识库正在处理，请稍后重试")
    return kb


def enqueue(db, kb, paths, background, cleanup=False):
    job = ImportJob(kb_id=kb.id, total=len(paths), source_paths=[str(Path(p).resolve()) for p in paths],
                    source_kind="upload" if cleanup else "local")
    kb.status = "indexing"
    db.add(job)
    db.commit()
    background.add_task(run_import, job.id, paths, cleanup)
    return {"job_id": job.id}


@app.post("/api/admin/knowledge-bases/{kb_id}/import-local", status_code=202)
def import_local(kb_id: str, body: PathInput, background: BackgroundTasks,
                 user: User = Depends(admin_user), db: Session = Depends(get_db)):
    kb = lock_kb(db, kb_id)
    try:
        paths = local_files(body.path)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return enqueue(db, kb, paths, background)


@app.post("/api/admin/knowledge-bases/{kb_id}/upload", status_code=202)
def upload(kb_id: str, background: BackgroundTasks, files: list[UploadFile] = File(...),
           user: User = Depends(admin_user), db: Session = Depends(get_db)):
    kb = lock_kb(db, kb_id)
    paths = save_uploads(files)
    try:
        return enqueue(db, kb, paths, background, cleanup=True)
    except Exception:
        cleanup_uploads(ImportJob(source_kind="upload", source_paths=[str(p) for p in paths]))
        raise


def save_uploads(files):
    # 新上传与旧任务重传共用校验，上传目录由服务器生成，不能由用户指定。
    if not files or len(files) > settings().max_import_files:
        raise HTTPException(400, "文件数量超出上限")
    root = settings().upload_dir
    if not root.is_absolute():
        root = ROOT / root
    folder = root / uid()
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    try:
        for uploaded in files:
            # 丢弃目录，拒绝异常名称及同批同名文件。
            name = Path((uploaded.filename or "").replace("\\", "/")).name
            if not name or len(name) > 255 or Path(name).suffix.lower() not in SUPPORTED or name in {p.name for p in paths}:
                raise HTTPException(400, "存在无效、重复或不支持的文件名")
            destination = folder / name
            paths.append(destination)
            size = 0
            with destination.open("wb") as target:
                while data := uploaded.file.read(1024 * 1024):
                    size += len(data)
                    if size > settings().max_file_mb * 1024 * 1024:
                        raise HTTPException(413, "单文件大小超出限制")
                    target.write(data)
        return paths
    except Exception:
        for path in paths:
            path.unlink(missing_ok=True)
        folder.rmdir()
        raise


@app.get("/api/admin/jobs")
def jobs(user: User = Depends(admin_user), db: Session = Depends(get_db)):
    rows = list(db.scalars(select(ImportJob).order_by(ImportJob.created_at.desc()).limit(30)))
    checkpoints = list(db.scalars(select(ImportCheckpoint).where(ImportCheckpoint.job_id.in_([j.id for j in rows]))))
    result = []
    for job in rows:
        saved = [c for c in checkpoints if c.job_id == job.id]
        result.append({"id": job.id, "kb_id": job.kb_id, "status": job.status, "total": job.total,
            "completed": job.completed, "chunks": job.chunks, "message": job.message,
            "total_chunks": sum(c.total_chunks for c in saved),
            "processed_chunks": sum(c.processed_chunks for c in saved),
            "vectorized_chunks": sum(c.vectorized_chunks for c in saved),
            "has_sources": bool(job.source_paths) and job.source_kind in {"local", "upload"}})
    return result


def inactive_job(db, job_id):
    found = db.get(ImportJob, job_id)
    if not found:
        raise HTTPException(404, "导入任务不存在")
    # 固定按知识库、任务的顺序加锁，避免与同库的新导入竞争。
    kb = db.scalar(select(KnowledgeBase).where(KnowledgeBase.id == found.kb_id).with_for_update())
    job = db.scalar(select(ImportJob).where(ImportJob.id == job_id).with_for_update().execution_options(populate_existing=True))
    if not job:
        raise HTTPException(404, "导入任务不存在")
    if job.status not in {"failed", "partial"}:
        raise HTTPException(409, "只有中断、失败或部分完成的任务可以重启或删除。")
    if db.get_bind().dialect.name == "mysql" and db.scalar(text("SELECT IS_USED_LOCK(:name)"), {"name": "bgw_job_" + job.id}) is not None:
        raise HTTPException(409, "任务仍在处理中，请稍后重试。")
    return job, kb


def restart_import(db, job, kb, paths, background, source_kind):
    if kb.status in {"indexing", "deleting"}:
        raise HTTPException(409, "知识库正在处理，请稍后重试。")
    old_sources = ImportJob(source_kind=job.source_kind, source_paths=job.source_paths)
    job.source_paths = [str(Path(p).resolve()) for p in paths]
    job.source_kind = source_kind
    job.status, job.total, job.completed, job.chunks = "queued", len(paths), 0, 0
    job.message = "任务已重新排队，已完成文档自动跳过，已保存片段继续处理。"
    kb.status = "indexing"
    db.commit()
    if old_sources.source_kind == "upload" and old_sources.source_paths != job.source_paths:
        cleanup_uploads(old_sources)
    background.add_task(run_import, job.id, paths, source_kind == "upload")
    return {"job_id": job.id}


@app.post("/api/admin/jobs/{job_id}/restart", status_code=202)
def restart_job(job_id: str, background: BackgroundTasks, body: ImportRetryInput = ImportRetryInput(),
                user: User = Depends(admin_user), db: Session = Depends(get_db)):
    job, kb = inactive_job(db, job_id)
    try:
        paths = local_files(body.path) if body.path else retry_files(job)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return restart_import(db, job, kb, paths, background, "local" if body.path else job.source_kind)


@app.post("/api/admin/jobs/{job_id}/publish-saved", status_code=202)
def publish_saved_job(job_id: str, background: BackgroundTasks,
                      user: User = Depends(admin_user), db: Session = Depends(get_db)):
    job, kb = inactive_job(db, job_id)
    if kb.status in {"indexing", "deleting"}:
        raise HTTPException(409, "知识库正在处理，请稍后重试。")
    saved = db.scalar(select(ImportCheckpoint.id).where(ImportCheckpoint.job_id == job.id,
        ImportCheckpoint.completed.is_(False), ImportCheckpoint.processed_chunks > 0).limit(1))
    if not saved:
        raise HTTPException(409, "没有尚待发布的已保存片段。")
    job.status, job.message, kb.status = "queued", "只发布已保存片段，后续抽取保持暂停。", "indexing"
    db.commit()
    background.add_task(run_publish_saved, job.id)
    return {"job_id": job.id}


@app.post("/api/admin/jobs/{job_id}/upload-retry", status_code=202)
def retry_job_upload(job_id: str, background: BackgroundTasks, files: list[UploadFile] = File(...),
                     user: User = Depends(admin_user), db: Session = Depends(get_db)):
    job, kb = inactive_job(db, job_id)
    if kb.status in {"indexing", "deleting"}:
        raise HTTPException(409, "知识库正在处理，请稍后重试。")
    paths = save_uploads(files)
    try:
        return restart_import(db, job, kb, paths, background, "upload")
    except Exception:
        cleanup_uploads(ImportJob(source_kind="upload", source_paths=[str(p) for p in paths]))
        raise


@app.delete("/api/admin/jobs/{job_id}")
def delete_job(job_id: str, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    job, _ = inactive_job(db, job_id)
    db.delete(job)
    db.commit()
    cleanup_uploads(job)
    return {"ok": True}


@app.delete("/api/admin/knowledge-bases/{kb_id}")
def delete_kb(kb_id: str, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    kb = db.scalar(select(KnowledgeBase).where(KnowledgeBase.id == kb_id).with_for_update())
    if not kb:
        raise HTTPException(404, "知识库不存在")
    if kb.status == "indexing":
        raise HTTPException(409, "导入期间不能删除知识库")
    kb.status = "deleting"
    db.commit()
    # 向量删除成功后才删除SQL；失败保持deleting状态，可再次删除重试。
    from .vectors import vector_store
    vector_store().delete_kb(kb.id)
    db.delete(kb)
    db.commit()
    return {"ok": True}


def locked_user(db, user):
    # MySQL行锁覆盖计划生成与答题提交，跨进程也能避免重复计划和复习推进。
    db.scalar(select(User).where(User.id == user.id).with_for_update())


def item_view(item):
    snapshot = dict(item.snapshot)
    if item.kind != "lesson" and not item.submitted:
        # 测验首次加载不下发答案，提交后才返回解析。
        for key in ("answer", "accepted_answers", "analysis"):
            snapshot.pop(key, None)
    return {"id": item.id, "kind": item.kind, "day": str(item.day), "is_review": item.is_review,
            "submitted": item.submitted, "correct": item.correct, "user_answer": item.user_answer,
            "kb_id": item.kb_id, "snapshot": snapshot}


def snapshot_of(db, concept):
    chunk = db.get(Chunk, concept.chunk_id)
    return {"title": concept.title, "category": concept.category, "depth": concept.depth,
        "question": concept.question, "answer": concept.answer, "analysis": concept.analysis,
        "source": chunk.source, "prerequisites": concept.prerequisite_titles}


@app.get("/api/dashboard")
def dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    progress = list(db.scalars(select(Progress).where(Progress.user_id == user.id)))
    daily = list(db.scalars(select(DailyItem).where(DailyItem.user_id == user.id, DailyItem.day == today())))
    attempts_rows = [i for i in daily if i.kind != "lesson" and i.submitted]
    history = list(db.execute(select(DailyItem.day, func.count()).where(DailyItem.user_id == user.id,
        DailyItem.submitted.is_(True), DailyItem.day >= today() - timedelta(days=6)).group_by(DailyItem.day)))
    return {"day": str(today()), "learned": len(progress),
        "due": sum(p.next_review <= today() for p in progress),
        "mistakes": sum(p.mistakes for p in progress),
        "lesson_done": sum(i.kind == "lesson" and i.submitted for i in daily),
        "lesson_total": sum(i.kind == "lesson" for i in daily),
        "quiz_done": len(attempts_rows), "quiz_total": sum(i.kind != "lesson" for i in daily),
        "accuracy": round(100 * sum(bool(i.correct) for i in attempts_rows) / len(attempts_rows)) if attempts_rows else None,
        "history": [{"day": str(day), "count": count} for day, count in history],
        "quiz_unlocked": any(p.first_learned < today() for p in progress)}


@app.get("/api/plans/{kind}")
def get_plan(kind: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if kind not in {"lesson", "quiz"}:
        raise HTTPException(404, "计划类型不存在")
    rows = db.scalars(select(DailyItem).where(DailyItem.user_id == user.id, DailyItem.day == today(),
        DailyItem.kind == "lesson" if kind == "lesson" else DailyItem.kind != "lesson").order_by(DailyItem.ordinal))
    return [item_view(i) for i in rows]


@app.get("/api/plans/quiz/generation")
def quiz_generation(user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = db.scalar(select(QuizGeneration).where(QuizGeneration.user_id == user.id, QuizGeneration.day == today()))
    return {"job": job_view(job) if job else None, "timezone": "Asia/Shanghai", "next_run": next_generation()}


@app.post("/api/plans/{kind}")
def create_plan(kind: str, body: PlanInput, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if kind not in {"lesson", "quiz"}:
        raise HTTPException(404, "计划类型不存在")
    if kind == "quiz":
        # HTTP仅负责入队并立即返回，客户端轮询进度，不等待13次模型调用。
        rows, job = app.state.quiz_service.enqueue(db, user.id, today(), more=body.more)
        db.commit()
        response.status_code = 202 if job else 200
        return {"items": [item_view(i) for i in rows], "added": 0, "job": job_view(job) if job else None}
    locked_user(db, user)
    existing = list(db.scalars(select(DailyItem).where(DailyItem.user_id == user.id, DailyItem.day == today(),
        DailyItem.kind == "lesson" if kind == "lesson" else DailyItem.kind != "lesson").order_by(DailyItem.ordinal)))
    if existing and not body.more:
        return {"items": [item_view(i) for i in existing], "added": 0}
    if len(existing) >= 100:
        raise HTTPException(400, "今日追加已达100条，请先完成现有内容")
    ready_ids = list(db.scalars(select(KnowledgeBase.id).where(KnowledgeBase.status == "ready")))
    concepts = list(db.scalars(select(Concept).where(Concept.kb_id.in_(ready_ids))))
    progress = {p.concept_id: p for p in db.scalars(select(Progress).where(Progress.user_id == user.id))}
    added = []
    selected = choose_lessons(concepts, progress, {i.concept_id for i in existing}, today(), min(10, 100 - len(existing)))
    for c, review in selected:
        added.append(DailyItem(user_id=user.id, kb_id=c.kb_id, concept_id=c.id, day=today(), kind="lesson",
            ordinal=len(existing) + len(added), snapshot=snapshot_of(db, c), is_review=review))
    db.add_all(added)
    db.commit()
    return {"items": [item_view(i) for i in existing + added], "added": len(added),
        "message": "当前可用知识不足10条，请导入更多资料或完成前置知识。" if kind == "lesson" and len(added) < 10 else ""}


def own_item(db, item_id, user):
    item = db.scalar(select(DailyItem).where(DailyItem.id == item_id, DailyItem.user_id == user.id))
    if not item:
        raise HTTPException(404, "题目不存在")
    return item


@app.post("/api/items/{item_id}/answer")
def submit(item_id: str, body: AnswerInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    locked_user(db, user)
    item = own_item(db, item_id, user)
    if item.day != today():
        raise HTTPException(409, "旧题已过期，请打开今日计划")
    if item.submitted:
        return item_view(item)
    if item.kind == "choice" and item.snapshot.get("option_order_version") is not None and body.option_order_version != item.snapshot["option_order_version"]:
        # 服务端调整未作答题目的选项后，拒绝旧页面按原位置提交，避免误判。
        raise HTTPException(409, "题目选项已更新，请刷新页面后重试")
    if not item.concept_id or not db.get(Concept, item.concept_id):
        raise HTTPException(409, "此题对应知识库已删除")
    if item.kind == "lesson":
        concept = db.get(Concept, item.concept_id)
        learned_ids = set(db.scalars(select(Progress.concept_id).where(Progress.user_id == user.id)))
        if concept.id not in learned_ids and any(p not in learned_ids for p in concept.prerequisites):
            raise HTTPException(409, "请先完成此题的前置知识")
        correct = body.remembered
    else:
        answers = [item.snapshot["answer"]] + item.snapshot.get("accepted_answers", [])
        correct = normalize_answer(body.answer) in {normalize_answer(a) for a in answers}
    item.submitted, item.correct, item.user_answer = True, correct, body.answer
    progress = db.scalar(select(Progress).where(Progress.user_id == user.id, Progress.concept_id == item.concept_id))
    if not progress:
        progress = Progress(user_id=user.id, concept_id=item.concept_id, first_learned=today(),
                            last_reviewed=today(), next_review=today() + timedelta(days=1), stage=0, mistakes=0)
        db.add(progress)
    review_update(progress, correct, today())
    db.commit()
    return item_view(item)


@app.get("/api/memory")
def memory(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(Progress, Concept).join(Concept, Progress.concept_id == Concept.id)
        .where(Progress.user_id == user.id).order_by(Progress.next_review, Progress.mistakes.desc()))
    return [{"title": c.title, "category": c.category, "next_review": str(p.next_review),
        "stage": p.stage, "mistakes": p.mistakes, "first_learned": str(p.first_learned)} for p, c in rows]


def conversation_for(db, item, user):
    convo = db.scalar(select(Conversation).where(Conversation.user_id == user.id, Conversation.item_id == item.id))
    if not convo:
        if item.day != today():
            raise HTTPException(410, "未收藏的昨日对话已重置")
        convo = Conversation(user_id=user.id, item_id=item.id, day=item.day, snapshot=item.snapshot)
        db.add(convo)
        db.flush()
    if convo.day != today() and not convo.saved:
        raise HTTPException(410, "未收藏的昨日对话已重置")
    return convo


def conversation_view(db, convo):
    item = db.get(DailyItem, convo.item_id)
    visible = dict(convo.snapshot)
    if item.kind != "lesson" and not item.submitted:
        for key in ("answer", "accepted_answers", "analysis"):
            visible.pop(key, None)
    return {"id": convo.id, "item_id": convo.item_id, "saved": convo.saved, "snapshot": visible,
        "item": item_view(item),
        "messages": [{"role": m.role, "content": m.content, "sources": m.sources, "ordinal": m.ordinal} for m in
            db.scalars(select(Message).where(Message.conversation_id == convo.id).order_by(Message.ordinal))]}


@app.get("/api/items/{item_id}/conversation")
def get_conversation(item_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    locked_user(db, user)
    # 访问今日计划时清理到期未收藏对话，跨日不会沿用旧上下文。
    db.execute(delete(Conversation).where(Conversation.user_id == user.id, Conversation.day < today(), Conversation.saved.is_(False)))
    convo = conversation_for(db, own_item(db, item_id, user), user)
    db.commit()
    return conversation_view(db, convo)


@app.post("/api/items/{item_id}/conversation")
def chat(item_id: str, body: ChatInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    locked_user(db, user)
    item = own_item(db, item_id, user)
    convo = conversation_for(db, item, user)
    history = [{"role": m.role, "content": m.content} for m in db.scalars(select(Message)
        .where(Message.conversation_id == convo.id).order_by(Message.ordinal))]
    if len(history) >= 200:
        raise HTTPException(400, "当前对话已达100轮上限")
    kb = db.get(KnowledgeBase, item.kb_id) if item.kb_id else None
    try:
        result = tutor_graph().invoke({"question": body.message, "snapshot": convo.snapshot,
            "kb_id": kb.id if kb and kb.status == "ready" else None, "history": history, "context": [], "reply": ""})
    except TutorUnavailable as exc:
        detail = "知识库检索暂不可用，请稍后重试或联系管理员。" if exc.stage == "retrieval" else "助教模型暂时无法响应，请稍后重试。"
        raise HTTPException(503, detail) from None
    # 只有模型成功后才提交问答对；失败重试不会制造孤立的用户消息。
    db.add(Message(conversation_id=convo.id, ordinal=len(history), role="user", content=body.message))
    db.flush()
    db.add(Message(conversation_id=convo.id, ordinal=len(history) + 1, role="assistant", content=result["reply"],
        sources=[{"index": i + 1, "source": c["source"]} for i, c in enumerate(result["context"])]))
    db.commit()
    return conversation_view(db, convo)


@app.post("/api/items/{item_id}/save")
def save(item_id: str, body: SaveInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    locked_user(db, user)
    convo = conversation_for(db, own_item(db, item_id, user), user)
    convo.saved = body.saved
    db.commit()
    return {"saved": convo.saved}


@app.get("/api/bookmarks")
def bookmarks(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [conversation_view(db, c) for c in db.scalars(select(Conversation)
        .where(Conversation.user_id == user.id, Conversation.saved.is_(True)).order_by(Conversation.day.desc()))]


app.mount("/assets", StaticFiles(directory=ROOT / "web"), name="assets")


@app.get("/")
def index():
    return FileResponse(ROOT / "web" / "index.html")
