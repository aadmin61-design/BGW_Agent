"""仅复制所需配置，不输出密钥，不复制原项目的数据库或向量集合。"""
from pathlib import Path
import secrets
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def reuse(source=Path("F:/Code/PapersManager/.env")):
    current = dotenv_values(ROOT / ".env") if (ROOT / ".env").exists() else {}
    template = dotenv_values(ROOT / ".env.example")
    original = dotenv_values(source)
    for key in ("LLM_API_URL", "LLM_API_KEY", "TEXT_MODEL", "EMBEDDING_MODEL", "MILVUS_URI", "MILVUS_TOKEN"):
        if original.get(key):
            template[key] = original[key]
    template.update(current)
    template["JWT_SECRET"] = template.get("JWT_SECRET") or secrets.token_urlsafe(48)
    # 使用 JSON 风格的双引号，正确保留 Windows 路径、引号和特殊字符。
    import json
    lines = [f"{key}={value if key == 'CORS_ORIGINS' else json.dumps(value or '', ensure_ascii=False)}"
             for key, value in template.items()]
    (ROOT / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("已写入本项目 .env；敏感值未显示。")


if __name__ == "__main__":
    reuse()
