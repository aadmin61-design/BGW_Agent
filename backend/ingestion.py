import hashlib
from pathlib import Path
from zipfile import ZipFile
from charset_normalizer import from_bytes
from sqlalchemy import select, text as sql_text
from langchain_text_splitters import RecursiveCharacterTextSplitter
from .config import settings
from .models import KnowledgeBase, ImportJob, Document, Chunk, Concept
from .database import session_factory
from .ai import extract_concepts
from .vectors import vector_store
from .scheduler import resolve_dependencies

SUPPORTED = {".pdf", ".docx", ".md", ".markdown", ".txt", ".rst", ".csv", ".json", ".yaml", ".yml", ".java", ".log"}
splitter = RecursiveCharacterTextSplitter(chunk_size=1800, chunk_overlap=180,
    separators=["\n# ", "\n## ", "\n\n", "\n", "。", " ", ""])


def parse_document(path):
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED:
        raise ValueError("不支持此文档类型")
    if path.stat().st_size > settings().max_file_mb * 1024 * 1024:
        raise ValueError("文件大小超出限制")
    sections = []
    if suffix == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise ValueError("暂不支持加密PDF，请先解密")
        if len(reader.pages) > 2500:
            raise ValueError("PDF页数超出限制")
        sections = [(page.extract_text() or "", f"{path.name} · 第{i + 1}页") for i, page in enumerate(reader.pages)]
    elif suffix == ".docx":
        from docx import Document as Docx
        # 在解压前限制总大小，避免压缩炸弹。
        with ZipFile(path) as archive:
            if sum(info.file_size for info in archive.infolist()) > 150 * 1024 * 1024:
                raise ValueError("DOCX解压大小超出限制")
        doc = Docx(path)
        # iter_inner_content 按原文顺序处理段落及表格。
        from docx.table import Table
        for i, block in enumerate(doc.iter_inner_content()):
            text = "\n".join(" | ".join(c.text for c in row.cells) for row in block.rows) if isinstance(block, Table) else block.text
            sections.append((text, f"{path.name} · 段落{i + 1}"))
        # 合并短段落以保留上下文，再按标题/段落切块。
        sections = [("\n\n".join(text for text, _ in sections), f"{path.name} · 正文")]
    else:
        decoded = from_bytes(path.read_bytes()).best()
        if decoded is None:
            raise ValueError("无法识别文本编码")
        sections = [(str(decoded), f"{path.name} · 正文")]
    chunks = [(text, source + f" · 片段{i + 1}") for content, source in sections
              for i, text in enumerate(splitter.split_text(content)) if text.strip()]
    if not chunks:
        raise ValueError("未提取到文字；扫描版PDF需先OCR")
    return chunks


def local_files(requested):
    root = settings().import_root.resolve()
    path = Path(requested).resolve()
    # resolve 防止 ../ 和符号链接绕过授权目录，绝不允许任意服务器路径。
    if not path.is_relative_to(root) or not path.exists():
        raise ValueError("只能导入配置的 IMPORT_ROOT 目录内的文件")
    candidates = [path] if path.is_file() else sorted(path.rglob("*"))
    files = [p for p in candidates if p.is_file() and p.suffix.lower() in SUPPORTED and p.resolve().is_relative_to(root)]
    if not files:
        raise ValueError("目录中没有支持的文档")
    if len(files) > settings().max_import_files:
        raise ValueError("文件数量超出单次导入上限，请选择子目录")
    return files


def upload_root():
    from .config import ROOT
    root = settings().upload_dir
    return (root if root.is_absolute() else ROOT / root).resolve()


def retry_files(job):
    if not job.source_paths or job.source_kind not in {"local", "upload"}:
        raise ValueError("此旧任务未保存原始文件位置，请重新选择同一批文档或目录。")
    root = upload_root() if job.source_kind == "upload" else settings().import_root.resolve()
    paths = [Path(value).resolve() for value in job.source_paths]
    if len(paths) > settings().max_import_files:
        raise ValueError("任务文件数量超出当前导入上限，请重新选择文档。")
    # 重试也检查授权目录、符号链接和文件可用性，不能用旧记录绕过路径限制。
    if any(not path.is_relative_to(root) or not path.is_file() or path.suffix.lower() not in SUPPORTED for path in paths):
        raise ValueError("原始文件不可用或不在授权目录内，请重新选择文档。")
    return paths


def cleanup_uploads(job):
    if job.source_kind != "upload":
        return
    root = upload_root()
    for value in job.source_paths or []:
        original = Path(value)
        resolved = original.resolve()
        # 仅清理任务持有的上传副本，先验证绝对路径；不递归删除、不触碰原始资料。
        if not resolved.is_relative_to(root) or resolved == root or original.is_symlink():
            continue
        try:
            original.unlink(missing_ok=True)
        except OSError:
            continue  # 副本暂时被占用不应撤销已成功的任务操作。
        try:
            original.parent.rmdir()  # 只删除已空的上传目录。
        except OSError:
            pass


def run_import(job_id, paths, cleanup=False):
    # 用单独连接持有任务租约；启动恢复仅清理已失去租约的中断任务。
    engine = session_factory().kw["bind"]
    with engine.connect() as lease:
        lock_name = "bgw_job_" + job_id
        acquired = lease.scalar(sql_text("SELECT GET_LOCK(:name, 0)"), {"name": lock_name})
        if acquired != 1:
            return
        try:
            _run_import(job_id, paths, cleanup)
        finally:
            lease.execute(sql_text("SELECT RELEASE_LOCK(:name)"), {"name": lock_name})


def _run_import(job_id, paths, cleanup=False):
    # 任务每个文档原子提交；失败时可以重传，已完成文档按摘要去重。
    with session_factory()() as db:
        job = db.get(ImportJob, job_id)
        kb = db.get(KnowledgeBase, job.kb_id)
        kb.status = "indexing"
        job.status = "running"
        db.commit()
        failed, skipped = [], 0
        for path in paths:
            path = Path(path)
            vector_ids = []
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                if db.scalar(select(Document).where(Document.kb_id == kb.id, Document.digest == digest)):
                    skipped += 1
                else:
                    pieces = parse_document(path)
                    doc = Document(kb_id=kb.id, name=path.name, digest=digest)
                    db.add(doc)
                    db.flush()
                    titles = list(db.scalars(select(Concept.title).where(Concept.kb_id == kb.id)))
                    for i, (text, source) in enumerate(pieces):
                        chunk = Chunk(kb_id=kb.id, doc_id=doc.id, text=text, source=source)
                        db.add(chunk)
                        db.flush()
                        extracted = extract_concepts(text, titles)
                        for value in extracted:
                            if value.title.strip().casefold() in {t.strip().casefold() for t in titles}:
                                continue
                            db.add(Concept(kb_id=kb.id, chunk_id=chunk.id, **value.model_dump(), prerequisites=[]))
                            titles.append(value.title)
                        # 提前记录id，即使网络超时但向量已写入，也能尝试补偿清理。
                        vector_ids.append(chunk.id)
                        vector_store().upsert([chunk])
                        message = f"正在处理 {path.name}：{i + 1}/{len(pieces)} 片段"
                        # 独立事务更新进度，不提交尚未完整导入的文档。
                        with session_factory()() as monitor:
                            status = monitor.get(ImportJob, job_id)
                            status.message = message
                            monitor.commit()
                    db.flush()
                    resolve_dependencies(list(db.scalars(select(Concept).where(Concept.kb_id == kb.id))))
                    job.chunks += len(pieces)
                    db.commit()
            except Exception:
                db.rollback()
                try:
                    vector_store().delete_chunks(vector_ids)
                except Exception:
                    pass
                # 不把SDK异常回显，避免URL、认证信息泄漏。可重试该文档。
                failed.append(path.name)
            job = db.get(ImportJob, job_id)
            job.completed += 1
            db.commit()
        kb = db.get(KnowledgeBase, job.kb_id)
        has_concepts = db.scalar(select(Concept.id).where(Concept.kb_id == kb.id).limit(1))
        kb.status = "ready" if has_concepts else "empty"
        job.status = "partial" if failed and has_concepts else "failed" if failed else "completed"
        job.message = (f"导入结束，跳过{skipped}个重复文件。" +
            ("失败文件：" + "、".join(failed) + "；请检查格式、模型与向量服务后重试。" if failed else ""))
        db.commit()
    if cleanup and job.status == "completed":
        # 失败/部分完成时保留上传副本，重试可继续去重；完成后才释放副本。
        cleanup_uploads(job)
