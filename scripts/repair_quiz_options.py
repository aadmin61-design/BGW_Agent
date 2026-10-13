"""仅调整今日未作答且没有收藏/聊天内容的旧选择题，先备份再提交。"""
import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select, func
from backend.config import settings
from backend.database import session_factory
from backend.models import User, DailyItem, Conversation, Message
from backend.quiz_options import balanced_targets, shuffle_choice


def repair(apply=False):
    day = datetime.now(ZoneInfo(settings().app_timezone)).date()
    backup, changed, skipped = [], 0, 0
    with session_factory()() as db:
        user_ids = list(db.scalars(select(DailyItem.user_id).where(DailyItem.day == day,
            DailyItem.kind == "choice").distinct()))
        for user_id in user_ids:
            # 与答题接口使用相同用户行锁，不能在用户提交答案时更改选项。
            db.scalar(select(User).where(User.id == user_id).with_for_update())
            rows = list(db.scalars(select(DailyItem).where(DailyItem.user_id == user_id,
                DailyItem.day == day, DailyItem.kind == "choice").order_by(DailyItem.ordinal).with_for_update()))
            eligible = []
            for item in rows:
                if item.submitted or item.snapshot.get("option_order_version"):
                    continue
                convo = db.scalar(select(Conversation).where(Conversation.item_id == item.id))
                # 已收藏快照和已有聊天可能引用旧选项字母，保持原题及其历史不变。
                if convo and (convo.saved or db.scalar(select(func.count()).select_from(Message)
                    .where(Message.conversation_id == convo.id))):
                    skipped += 1
                    continue
                eligible.append((item, convo))
            ids = {item.id for item, _ in eligible}
            fixed = Counter(item.snapshot["answer"] for item in rows if item.id not in ids)
            targets = balanced_targets(len(eligible), fixed)
            for (item, convo), target in zip(eligible, targets, strict=True):
                result = shuffle_choice(item.snapshot, target)
                backup.append({"item_id": item.id, "snapshot": item.snapshot,
                    "conversation_id": convo.id if convo else None,
                    "conversation_snapshot": convo.snapshot if convo else None})
                if apply:
                    item.snapshot = result
                    if convo:
                        convo.snapshot = result
                changed += 1
        if apply and backup:
            folder = settings().upload_dir.parent / "data" / "maintenance"
            folder.mkdir(mode=0o700, parents=True, exist_ok=True)
            path = folder / f"quiz-options-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.json"
            # 写入私有备份失败就不提交数据库；重复执行不会再次排列已更新题目。
            with path.open("x", encoding="utf-8") as file:
                json.dump(backup, file, ensure_ascii=False)
            path.chmod(0o600)
            db.commit()
        else:
            db.rollback()
    print(json.dumps({"applied": apply, "changed": changed, "preserved_chat_or_saved": skipped}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    repair(parser.parse_args().apply)
