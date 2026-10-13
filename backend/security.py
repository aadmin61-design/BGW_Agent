from datetime import datetime, timezone, timedelta
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from pwdlib import PasswordHash
import jwt
from .config import settings
from .database import get_db
from .models import User

passwords = PasswordHash.recommended()


def token(user):
    cfg = settings()
    if len(cfg.jwt_secret) < 32:
        raise HTTPException(503, "JWT_SECRET 至少需要 32 个字符")
    return jwt.encode({"sub": user.id, "exp": datetime.now(timezone.utc) + timedelta(days=7)},
                      cfg.jwt_secret, algorithm="HS256")


def current_user(request: Request, db: Session = Depends(get_db)):
    try:
        decoded = jwt.decode(request.cookies.get("bgw_session", ""), settings().jwt_secret, algorithms=["HS256"])
        user = db.scalar(select(User).where(User.id == decoded["sub"]))
    except (jwt.InvalidTokenError, KeyError):
        user = None
    if not user:
        raise HTTPException(401, "请先登录")
    return user


def admin_user(user: User = Depends(current_user)):
    if not user.is_admin:
        raise HTTPException(403, "仅管理员可管理知识库")
    return user
