"""显式初始化数据库或创建管理员；不允许通过公开注册取得管理员角色。"""
import argparse
import getpass
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import create_engine, URL, text, select
from backend.config import settings
from backend.database import session_factory
from backend.models import Base, User
from backend.security import passwords
from backend.migrations import migrate_message_order


def init_db():
    cfg = settings()
    if cfg.mysql_database != "bgw_agent":
        raise ValueError("初始化脚本只允许创建独立的 bgw_agent 数据库")
    engine = create_engine(URL.create("mysql+pymysql", username=cfg.mysql_user, password=cfg.mysql_password,
        host=cfg.mysql_host, port=cfg.mysql_port))
    with engine.begin() as conn:
        conn.execute(text("CREATE DATABASE IF NOT EXISTS bgw_agent CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))
    with session_factory()() as db:
        Base.metadata.create_all(db.get_bind())
        migrate_message_order(db.get_bind())
    print("bgw_agent 数据库及表已就绪。")


def create_admin(username):
    password = getpass.getpass("管理员密码（不显示）：")
    if len(password) < 12:
        raise ValueError("管理员密码至少12个字符")
    with session_factory()() as db:
        if db.scalar(select(User).where(User.username == username)):
            raise ValueError("此用户名已存在；为避免意外提权，请使用新的管理员用户名")
        db.add(User(username=username, password_hash=passwords.hash(password), is_admin=True))
        db.commit()
    print("管理员已创建。")


def bootstrap_admin(username):
    import secrets
    output = Path(__file__).resolve().parents[1] / "data" / "admin-credentials.txt"
    with session_factory()() as db:
        if db.scalar(select(User).where(User.username == username)):
            print("管理员用户名已存在，保留原密码。")
            return
        password = secrets.token_urlsafe(18)
        db.add(User(username=username, password_hash=passwords.hash(password), is_admin=True))
        db.commit()
    output.parent.mkdir(parents=True, exist_ok=True)
    # 初始登录凭据只写入被忽略的本机文件，不输出到日志或接口。
    output.write_text(f"用户名: {username}\n密码: {password}\n", encoding="utf-8")
    print("管理员已创建，凭据保存在 data/admin-credentials.txt。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["init-db", "create-admin", "bootstrap-admin"])
    parser.add_argument("--username", default="admin")
    args = parser.parse_args()
    try:
        if args.command == "init-db":
            init_db()
        elif args.command == "create-admin":
            create_admin(args.username)
        else:
            bootstrap_admin(args.username)
    except Exception:
        # 不输出异常连接串；错误原因可以检查配置或服务状态。
        print("操作失败，请检查配置/权限/服务，或用户名及密码要求。", file=sys.stderr)
        sys.exit(1)
