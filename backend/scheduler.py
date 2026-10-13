"""独立、无模型调用的计划排序和间隔复习规则。"""
from datetime import timedelta
import re
import unicodedata

INTERVALS = (1, 3, 7, 14, 30, 60)


def normalize_answer(value: str) -> str:
    # 兼容全半角、大小写及空白，但不删除有语义的标点。
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).casefold()


def review_update(progress, correct: bool, today):
    if correct:
        # 一天内多个相关练习只推进一次间隔，避免重复点击跳过复习。
        if progress.last_reviewed != today:
            progress.stage = min(progress.stage + 1, len(INTERVALS) - 1)
    else:
        progress.stage = 0
        progress.mistakes += 1
    progress.last_reviewed = today
    progress.next_review = today + timedelta(days=INTERVALS[progress.stage])


def choose_lessons(concepts, progress, excluded, today, count=10):
    by_id = {c.id: c for c in concepts}
    learned = set(progress)
    # 错题和到期复习排在新知识前；旧计划中的概念不会在同一天重复追加。
    due = [c for c in concepts if c.id in progress and progress[c.id].next_review <= today and c.id not in excluded]
    due.sort(key=lambda c: (-progress[c.id].mistakes, progress[c.id].next_review, c.depth, c.title))
    chosen = [(c, True) for c in due[:count]]
    available = learned | set(excluded) | {c.id for c, _ in chosen}
    pending = sorted([c for c in concepts if c.id not in learned and c.id not in excluded],
                     key=lambda c: (c.depth, c.category, c.title))
    while pending and len(chosen) < count:
        candidate = next((c for c in pending if all(p in available or p not in by_id for p in c.prerequisites)), None)
        if candidate is None:
            break
        pending.remove(candidate)
        chosen.append((candidate, False))
        available.add(candidate.id)
    return chosen


def resolve_dependencies(concepts):
    # 只接受已知且排位更早的概念，防止模型生成自依赖或循环依赖。
    ordered = sorted(concepts, key=lambda c: (c.depth, c.title, c.id))
    known = {}
    for concept in ordered:
        concept.prerequisites = list(dict.fromkeys(known[t.strip().casefold()]
            for t in concept.prerequisite_titles if t.strip().casefold() in known))
        known.setdefault(concept.title.strip().casefold(), concept.id)
