"""通过本机Unix Socket初始化专属数据库，不把密码放到命令行。"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sqlalchemy import create_engine, text, URL
from backend.config import settings

cfg = settings()
if cfg.mysql_database != "bgw_agent" or cfg.mysql_user != "bgw":
    raise ValueError("服务器只能初始化本项目的bgw账号与数据库")
engine = create_engine(URL.create("mysql+pymysql", username="root",
    query={"unix_socket": "/var/run/mysqld/mysqld.sock"}), hide_parameters=True)
with engine.begin() as conn:
    exists = conn.scalar(text("SELECT COUNT(*) FROM mysql.user WHERE User='bgw' AND Host='localhost'"))
    if exists:
        # 不替换已有数据库账号的凭证，避免误伤其他应用或既有安装。
        raise ValueError("bgw数据库账号已存在，请先核对目标服务器")
    conn.execute(text("CREATE DATABASE IF NOT EXISTS bgw_agent CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))
    conn.execute(text("CREATE USER 'bgw'@'localhost' IDENTIFIED BY :password"), {"password": cfg.mysql_password})
    conn.execute(text("GRANT ALL PRIVILEGES ON bgw_agent.* TO 'bgw'@'localhost'"))
engine.dispose()
print("服务器专属数据库账号已配置。")
