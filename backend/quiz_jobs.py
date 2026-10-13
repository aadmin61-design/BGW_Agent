"""持久化测验队列：北京时间6点入队，模型调用不占用HTTP请求或用户行锁。"""
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from sqlalchemy import select, update
from .models import User, KnowledgeBase, Concept, Chunk, Progress, DailyItem, QuizGeneration, uid, utcnow
from .quiz_options import balanced_targets, shuffle_choice

QUIZ_ZONE = ZoneInfo("Asia/Shanghai")
ACTIVE = {"queued", "running"}


def local_now(now=None):
    return (now or datetime.now(timezone.utc)).astimezone(QUIZ_ZONE)


def next_generation(now=None):
    current = local_now(now)
    target = current.replace(hour=6, minute=0, second=0, microsecond=0)
    if current >= target:
        target += timedelta(days=1)
    return target.isoformat()


def job_view(job):
    return {"id": job.id, "day": str(job.day), "status": job.status, "source": job.source,
            "more": job.more, "total": job.total, "completed": job.completed, "message": job.message}


def quiz_rows(db, user_id, day, lock=False):
    query = select(DailyItem).where(DailyItem.user_id == user_id,
        DailyItem.day == day, DailyItem.kind != "lesson").order_by(DailyItem.ordinal)
    # MySQL默认可重复读下，写操作需当前读，不能沿用鉴权时建立的旧快照。
    return list(db.scalars(query.with_for_update() if lock else query))


def candidates(db, user_id, day):
    return list(db.execute(select(Concept, Progress).join(Progress, Progress.concept_id == Concept.id)
        .join(KnowledgeBase, KnowledgeBase.id == Concept.kb_id).where(Progress.user_id == user_id,
        Progress.first_learned < day, KnowledgeBase.status == "ready")
        .order_by((Progress.next_review > day), Progress.mistakes.desc(), Progress.next_review, Concept.depth, Concept.id)))


class QuizService:
    def __init__(self, factory, generate, day_fn=None):
        self.factory, self.generate = factory, generate
        self.day = day_fn or (lambda: local_now().date())
        self.stop = asyncio.Event()

    def enqueue(self, db, user_id, day, more=False, source="manual"):
        # 手动、定时与多进程都先短暂锁定用户，合并重复请求；出题阶段释放锁。
        db.scalar(select(User).where(User.id == user_id).with_for_update())
        job = db.scalar(select(QuizGeneration).where(QuizGeneration.user_id == user_id, QuizGeneration.day == day).with_for_update())
        rows = quiz_rows(db, user_id, day, lock=True)
        if job and job.status in ACTIVE:
            return rows, job
        if rows and not more:
            return rows, None
        if len(rows) >= 100:
            raise HTTPException(400, "今日追加已达100条，请先完成现有内容")
        if not candidates(db, user_id, day):
            raise HTTPException(409, "完成学习后，第二天解锁测验")
        if job is None:
            job = QuizGeneration(user_id=user_id, day=day)
            db.add(job)
        job.status, job.source, job.more = "queued", source, more
        job.base_count, job.total, job.completed = len(rows), min(13, 100 - len(rows)), 0
        job.run_id, job.expires_at, job.message = None, None, "等待生成，可继续浏览其他页面。"
        db.flush()
        return rows, job

    def enqueue_due(self, now=None):
        current = local_now(now)
        with self.factory() as db:
            # 旧日期与失去心跳的运行任务明确失败，绝不长期留在加载状态。
            db.execute(update(QuizGeneration).where(
                QuizGeneration.status.in_(ACTIVE),
                (QuizGeneration.day < current.date()) | ((QuizGeneration.status == "running") &
                 (QuizGeneration.expires_at < utcnow()))).values(status="failed", message="生成已中断或超时，请手动重试。"))
            db.commit()
            if current.hour < 6:
                return 0
            users = list(db.scalars(select(Progress.user_id).join(Concept, Concept.id == Progress.concept_id)
                .join(KnowledgeBase, KnowledgeBase.id == Concept.kb_id).where(
                Progress.first_learned < current.date(), KnowledgeBase.status == "ready").distinct()))
        count = 0
        for user_id in users:
            with self.factory() as db:
                db.scalar(select(User).where(User.id == user_id).with_for_update())
                # 每日只自动尝试一次；失败可由用户重试，避免定时器反复消耗模型额度。
                if db.scalar(select(QuizGeneration.id).where(QuizGeneration.user_id == user_id,
                       QuizGeneration.day == current.date()).with_for_update()) or quiz_rows(db, user_id, current.date(), lock=True):
                    continue
                try:
                    self.enqueue(db, user_id, current.date(), source="automatic")
                    db.commit()
                    count += 1
                except HTTPException:
                    db.rollback()
        return count

    def claim_next(self):
        with self.factory() as db:
            job_id = db.scalar(select(QuizGeneration.id).where(QuizGeneration.status == "queued",
                QuizGeneration.day == self.day()).order_by(QuizGeneration.created_at).limit(1))
            if not job_id:
                return None
            run_id = uid()
            # 条件更新抢占，多个服务进程也不会同时执行同一批次。
            changed = db.execute(update(QuizGeneration).where(QuizGeneration.id == job_id,
                QuizGeneration.status == "queued").values(status="running", run_id=run_id,
                expires_at=utcnow() + timedelta(seconds=240), message="正在生成题目，可继续浏览其他页面。"))
            db.commit()
            return (job_id, run_id) if changed.rowcount == 1 else None

    def _active(self, job, run_id):
        return job and job.run_id == run_id and job.status == "running" and job.day == self.day() and job.expires_at >= utcnow()

    def _fail(self, job_id, run_id, message):
        with self.factory() as db:
            db.execute(update(QuizGeneration).where(QuizGeneration.id == job_id,
                QuizGeneration.run_id == run_id, QuizGeneration.status == "running")
                .values(status="failed", message=message))
            db.commit()

    def run_job(self, job_id, run_id):
        pool = None
        try:
            with self.factory() as db:
                job = db.get(QuizGeneration, job_id)
                if not self._active(job, run_id):
                    return
                learned = candidates(db, job.user_id, job.day)
                if not learned:
                    raise ValueError("没有可用的已学知识")
                work = []
                for i, kind in enumerate((["choice"] * 10 + ["fill"] * 3)[:job.total]):
                    concept = learned[(job.base_count + i) % len(learned)][0]
                    chunk = db.get(Chunk, concept.chunk_id)
                    snapshot = {"title": concept.title, "category": concept.category, "depth": concept.depth,
                        "question": concept.question, "answer": concept.answer, "analysis": concept.analysis,
                        "source": chunk.source, "prerequisites": concept.prerequisite_titles}
                    work.append((concept, kind, snapshot))
                user_id, day, base_count = job.user_id, job.day, job.base_count
            # 限制为三个并发调用，整批180秒截止；不在网络等待期间持有SQL事务。
            pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="quiz-model")
            futures = {pool.submit(self.generate, concept, kind, base_count + i + 1): i
                       for i, (concept, kind, _) in enumerate(work)}
            results = {}
            for future in as_completed(futures, timeout=180):
                results[futures[future]] = future.result()
                with self.factory() as db:
                    changed = db.execute(update(QuizGeneration).where(QuizGeneration.id == job_id,
                        QuizGeneration.run_id == run_id, QuizGeneration.status == "running",
                        QuizGeneration.day == self.day(), QuizGeneration.expires_at >= utcnow())
                        .values(completed=len(results)))
                    if changed.rowcount != 1:
                        return
                    db.commit()
            with self.factory() as db:
                db.scalar(select(User).where(User.id == user_id).with_for_update())
                current = db.scalar(select(QuizGeneration).where(QuizGeneration.id == job_id).with_for_update())
                if not self._active(current, run_id):
                    return
                if len(quiz_rows(db, user_id, day, lock=True)) != base_count:
                    raise ValueError("计划已发生变化")
                live_ids = set(db.scalars(select(Concept.id).join(KnowledgeBase).where(KnowledgeBase.status == "ready")))
                if any(concept.id not in live_ids for concept, _, _ in work):
                    raise ValueError("知识库已变更")
                # 整批校验成功后一次性提交，失败不会遗留半套测验或泄露答案。
                targets = iter(balanced_targets(sum(kind == "choice" for _, kind, _ in work)))
                for i, (concept, kind, snapshot) in enumerate(work):
                    result = shuffle_choice(results[i], next(targets)) if kind == "choice" else results[i]
                    db.add(DailyItem(user_id=user_id, kb_id=concept.kb_id, concept_id=concept.id,
                        day=day, kind=kind, ordinal=base_count + i, snapshot={**snapshot, **result}, is_review=True))
                current.status, current.message = "completed", "今日测验已准备好。"
                db.commit()
        except FuturesTimeout:
            self._fail(job_id, run_id, "生成超时，请重试；本次未写入不完整题目。")
        except ValueError:
            self._fail(job_id, run_id, "题目校验失败或知识库发生变更，请重试。")
        except Exception:
            # 不将供应商响应、数据库连接信息或密钥写入任务提示。
            self._fail(job_id, run_id, "生成失败，请稍后重试或检查模型服务。")
        finally:
            if pool:
                pool.shutdown(wait=False, cancel_futures=True)

    async def _wait(self, seconds):
        try:
            await asyncio.wait_for(self.stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    async def _schedule(self):
        while not self.stop.is_set():
            try:
                await asyncio.to_thread(self.enqueue_due)
            except Exception:
                pass  # 数据库短暂失联时稍后重试，定时器不退出。
            await self._wait(15)

    async def _worker(self):
        while not self.stop.is_set():
            try:
                ticket = await asyncio.to_thread(self.claim_next)
                if ticket:
                    await asyncio.to_thread(self.run_job, *ticket)
                    continue
            except Exception:
                pass
            await self._wait(2)

    async def run(self):
        # 定时入队和消费分开，正在出题时仍能准时触发6点计划。
        await asyncio.gather(self._schedule(), self._worker())
