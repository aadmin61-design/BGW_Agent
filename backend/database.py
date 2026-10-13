from functools import lru_cache
from sqlalchemy import create_engine, URL
from sqlalchemy.orm import sessionmaker
from .config import settings


@lru_cache
def session_factory():
    cfg = settings()
    if not cfg.mysql_user:
        raise RuntimeError("请先填写 .env 中的 MySQL 配置")
    # URL.create 自动编码密码；该项目只使用独立数据库，不操作其他项目表。
    url = URL.create("mysql+pymysql", username=cfg.mysql_user, password=cfg.mysql_password,
                     host=cfg.mysql_host, port=cfg.mysql_port, database=cfg.mysql_database,
                     query={"charset": "utf8mb4"})
    engine = create_engine(url, pool_pre_ping=True, pool_recycle=1800)
    return sessionmaker(engine, expire_on_commit=False)


def get_db():
    with session_factory()() as db:
        yield db
