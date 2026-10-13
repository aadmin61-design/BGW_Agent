from pathlib import Path
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AliasChoices, Field

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    # 只从后端读取敏感信息，绝不把配置返回给前端。
    llm_api_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_api_key: str = ""
    text_model: str = "qwen-plus"
    embedding_model: str = "text-embedding-v4"
    embedding_dimensions: int = 1024
    # VECTOR_URI避免SDK自行读取MILVUS_URI时把Lite文件误判成远程地址。
    # 保留旧变量别名，本机原有Milvus服务无需改配置。
    milvus_uri: str = Field(default="http://127.0.0.1:19530",
                           validation_alias=AliasChoices("VECTOR_URI", "MILVUS_URI"))
    milvus_token: str = ""
    milvus_collection: str = "bgw_knowledge_v1"
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = ""
    mysql_password: str = ""
    mysql_database: str = "bgw_agent"
    jwt_secret: str = ""
    cookie_secure: bool = False
    cors_origins: list[str] = ["http://localhost:8001", "http://127.0.0.1:8001"]
    import_root: Path = Path("F:/Java八股文")
    upload_dir: Path = ROOT / "uploads"
    app_timezone: str = "Asia/Shanghai"
    max_file_mb: int = 30
    max_import_files: int = 100
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore", env_file_encoding="utf-8")


@lru_cache
def settings():
    return Settings()
