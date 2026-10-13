"""用真实资料的一小段验证完整入库链路，不处理整个资料目录。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from docx import Document as Docx
from sqlalchemy import select, func
from backend.config import ROOT, settings
from backend.database import session_factory
from backend.models import KnowledgeBase, ImportJob, Concept
from backend.ingestion import run_import


def smoke():
    source = next(settings().import_root.rglob("*.docx"))
    doc = Docx(source)
    content = "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())[:6500]
    folder = ROOT / "data" / "smoke"
    folder.mkdir(parents=True, exist_ok=True)
    sample = folder / "Java真实资料节选.md"
    sample.write_text(f"# 验证节选：{source.name}\n\n仅截取前6500字符进行小规模链路验证。\n\n" + content, encoding="utf-8")
    with session_factory()() as db:
        kb = db.scalar(select(KnowledgeBase).where(KnowledgeBase.name == "Java 面试知识库 · 真实节选"))
        if not kb:
            kb = KnowledgeBase(name="Java 面试知识库 · 真实节选", description="来自本地DOCX前6500字符的小规模验证，非完整资料。完整文档请通过管理页面导入。")
            db.add(kb); db.flush()
        job = ImportJob(kb_id=kb.id, total=1); db.add(job); db.commit()
        job_id, kb_id = job.id, kb.id
    run_import(job_id, [sample])
    with session_factory()() as db:
        job = db.get(ImportJob, job_id)
        count = db.scalar(select(func.count()).select_from(Concept).where(Concept.kb_id == kb_id))
        print(f"status={job.status}; concepts={count}; chunks={job.chunks}", flush=True)
        if job.status not in {"completed", "partial"} or not count:
            sys.exit(1)


if __name__ == "__main__":
    smoke()
