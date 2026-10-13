import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from zipfile import ZipFile
from charset_normalizer import from_bytes
from sqlalchemy import select, delete, func, text as sql_text
from langchain_text_splitters import RecursiveCharacterTextSplitter
from .config import settings
from .models import KnowledgeBase, ImportJob, Document, Chunk, Concept, ImportCheckpoint, ImportPiece, utcnow
from .database import session_factory
from .ai import extract_concepts, ExtractedConcept
from .vectors import vector_store
from .scheduler import resolve_dependencies

SUPPORTED = {".pdf", ".docx", ".md", ".markdown", ".txt", ".rst", ".csv", ".json", ".yaml", ".yml", ".java", ".log"}
splitter = RecursiveCharacterTextSplitter(chunk_size=1800, chunk_overlap=180,
    separators=["\n# ", "\n## ", "\n\n", "\n", "。", " ", ""])

PARSER_VERSION = 2


def docx_text(element):
    """按XML顺序读取正文、表格和图形文本，兼容分支只取一份可见内容。"""
    word = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    drawing = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    compatibility = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
    if element.tag in {word + "t", drawing + "t"}:
        return element.text or ""
    if element.tag in {word + "del", word + "moveFrom"}:
        return ""
    if element.tag == compatibility + "AlternateContent":
        # DrawingML和VML回退通常包含同一段文字，不能把两份重复收录。
        for branch in element:
            value = docx_text(branch)
            if value.strip():
                return value
        return ""
    if element.tag in {word + "br", word + "cr", drawing + "br"}:
        return "\n"
    if element.tag == word + "tab":
        return "\t"
    if element.tag == word + "tbl":
        return "\n".join(" | ".join(docx_text(cell).strip() for cell in row if cell.tag == word + "tc")
            for row in element if row.tag == word + "tr") + "\n\n"
    content = "".join(docx_text(child) for child in element)
    return content + ("\n\n" if element.tag in {word + "p", drawing + "p"} else "")


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
        # Paragraph.text遗漏文本框及内容控件，直接遍历正文XML，保留图中可提取文字。
        sections = [(docx_text(doc.element.body), f"{path.name} · 正文")]
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


class ImportFailure(RuntimeError):
    def __init__(self, stage, ordinal, error):
        # 只保存故障阶段、位置和异常类型，不保存含凭据的供应商响应。
        self.detail = f"{stage}阶段，第{ordinal}片段，异常类型{type(error).__name__}"
        super().__init__(self.detail)


def _extract_retry(text, titles, extractor):
    retryable = {"OutputParserException", "ValidationError", "RateLimitError", "APIConnectionError",
                 "APITimeoutError", "InternalServerError"}
    for attempt in range(3):
        try:
            return extractor(text, titles)
        except Exception as error:
            if type(error).__name__ not in retryable or attempt == 2:
                raise
            time.sleep(attempt + 1)


def _prepare_checkpoint(job_id, kb_id, path, digest, pieces):
    with session_factory()() as db:
        if db.scalar(select(Document.id).where(Document.kb_id == kb_id, Document.digest == digest)):
            return None
        checkpoint = db.scalar(select(ImportCheckpoint).where(ImportCheckpoint.kb_id == kb_id,
            ImportCheckpoint.digest == digest))
        if not checkpoint:
            checkpoint = ImportCheckpoint(kb_id=kb_id, job_id=job_id, digest=digest,
                name=path.name, total_chunks=len(pieces), parser_version=PARSER_VERSION)
            db.add(checkpoint)
        else:
            checkpoint.job_id = job_id
            if checkpoint.parser_version != PARSER_VERSION or checkpoint.total_chunks != len(pieces):
                # 解析规则变化后不能沿用旧位置的缓存，正式知识仍不受影响。
                db.execute(delete(ImportPiece).where(ImportPiece.checkpoint_id == checkpoint.id))
                checkpoint.parser_version = PARSER_VERSION
                checkpoint.total_chunks, checkpoint.processed_chunks = len(pieces), 0
                checkpoint.vectorized_chunks = 0
        db.commit()
        return checkpoint.id


def _extract_document(job_id, kb_id, checkpoint_id, pieces):
    with session_factory()() as db:
        saved = list(db.scalars(select(ImportPiece).where(ImportPiece.checkpoint_id == checkpoint_id)
            .order_by(ImportPiece.ordinal)))
        cached = {piece.ordinal for piece in saved}
        titles = list(db.scalars(select(Concept.title).where(Concept.kb_id == kb_id)))
        titles.extend(value["title"] for piece in saved for value in piece.concepts)
    todo = [i for i in range(len(pieces)) if i not in cached]
    pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="import-extract")
    futures = {}
    try:
        for index in todo[:2]:
            futures[index] = pool.submit(_extract_retry, pieces[index][0], list(titles), extract_concepts)
        for offset, index in enumerate(todo):
            try:
                extracted = futures.pop(index).result()
            except Exception as error:
                raise ImportFailure("知识提取", index + 1, error) from None
            # 临时片段单独提交，正式Document/Chunk/Concept仍以整篇文档原子发布。
            with session_factory()() as db:
                db.add(ImportPiece(checkpoint_id=checkpoint_id, ordinal=index, text=pieces[index][0],
                    source=pieces[index][1], concepts=[value.model_dump() for value in extracted]))
                db.flush()
                checkpoint = db.get(ImportCheckpoint, checkpoint_id)
                checkpoint.processed_chunks = db.scalar(select(func.count()).select_from(ImportPiece)
                    .where(ImportPiece.checkpoint_id == checkpoint_id))
                checkpoint.updated_at = utcnow()
                job = db.get(ImportJob, job_id)
                job.message = f"正在提取 {checkpoint.name}：{checkpoint.processed_chunks}/{len(pieces)} 片段（进度已保存）"
                db.commit()
            titles.extend(value.title for value in extracted)
            if offset + 2 < len(todo):
                next_index = todo[offset + 2]
                futures[next_index] = pool.submit(_extract_retry, pieces[next_index][0], list(titles), extract_concepts)
    finally:
        # 未开始的请求取消；在途请求只返回数据，不会自行修改SQL或向量。
        pool.shutdown(wait=False, cancel_futures=True)


def _publish_document(job_id, kb_id, checkpoint_id):
    with session_factory()() as db:
        checkpoint = db.get(ImportCheckpoint, checkpoint_id)
        saved = list(db.scalars(select(ImportPiece).where(ImportPiece.checkpoint_id == checkpoint_id)
            .order_by(ImportPiece.ordinal)))
        if len(saved) != checkpoint.total_chunks or [piece.ordinal for piece in saved] != list(range(checkpoint.total_chunks)):
            raise ValueError("片段尚未完整提取，不能发布文档")
        name, digest = checkpoint.name, checkpoint.digest
    chunks = [Chunk(id=piece.chunk_id, kb_id=kb_id, doc_id=checkpoint_id,
                    text=piece.text, source=piece.source) for piece in saved]
    attempted = []
    try:
        # 云端嵌入等待期间不持有正式知识表事务；按小批量写入以控制内存和请求数。
        for offset in range(0, len(chunks), 8):
            batch = chunks[offset:offset + 8]
            attempted.extend(chunk.id for chunk in batch)
            vector_store().upsert(batch)
            with session_factory()() as db:
                db.get(ImportCheckpoint, checkpoint_id).vectorized_chunks = min(offset + 8, len(chunks))
                db.get(ImportJob, job_id).message = f"正在写入 {name} 的向量：{min(offset + 8, len(chunks))}/{len(chunks)} 片段"
                db.commit()
        with session_factory()() as db:
            db.add(Document(id=checkpoint_id, kb_id=kb_id, name=name, digest=digest))
            db.flush()
            db.add_all(chunks)
            db.flush()
            titles = set(title.strip().casefold() for title in db.scalars(select(Concept.title).where(Concept.kb_id == kb_id)))
            for piece in saved:
                for data in piece.concepts:
                    value = ExtractedConcept.model_validate(data)
                    normalized = value.title.strip().casefold()
                    if not normalized or normalized in titles:
                        continue
                    db.add(Concept(kb_id=kb_id, chunk_id=piece.chunk_id, **value.model_dump(), prerequisites=[]))
                    titles.add(normalized)
            db.flush()
            resolve_dependencies(list(db.scalars(select(Concept).where(Concept.kb_id == kb_id))))
            db.get(ImportCheckpoint, checkpoint_id).completed = True
            db.get(ImportJob, job_id).chunks += len(chunks)
            # 与正式文档同一次提交清理临时结果，提交失败仍可恢复全部抽取进度。
            db.execute(delete(ImportPiece).where(ImportPiece.checkpoint_id == checkpoint_id))
            db.commit()
    except Exception as error:
        # 提交确认丢失时先检查SQL结果，不能删除实际上已经发布的向量。
        with session_factory()() as db:
            committed = db.get(Document, checkpoint_id) is not None
        if committed:
            return
        try:
            vector_store().delete_chunks(attempted)
        except Exception:
            pass
        with session_factory()() as db:
            db.get(ImportCheckpoint, checkpoint_id).vectorized_chunks = 0
            db.commit()
        raise ImportFailure("向量或发布", len(attempted), error) from None


def _run_import(job_id, paths, cleanup=False):
    with session_factory()() as db:
        job = db.get(ImportJob, job_id)
        kb_id = job.kb_id
        db.get(KnowledgeBase, kb_id).status = "indexing"
        job.status = "running"
        db.commit()
    failed, skipped = [], 0
    for path in map(Path, paths):
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            pieces = parse_document(path)
            checkpoint_id = _prepare_checkpoint(job_id, kb_id, path, digest, pieces)
            if checkpoint_id is None:
                skipped += 1
            else:
                _extract_document(job_id, kb_id, checkpoint_id, pieces)
                _publish_document(job_id, kb_id, checkpoint_id)
        except Exception as error:
            # 首次失败也留下明确阶段；不返回原始异常正文或供应商连接信息。
            detail = error.detail if isinstance(error, ImportFailure) else f"解析或缓存阶段，异常类型{type(error).__name__}"
            failed.append(f"{path.name}（{detail}）")
        with session_factory()() as db:
            db.get(ImportJob, job_id).completed += 1
            db.commit()
    with session_factory()() as db:
        kb, job = db.get(KnowledgeBase, kb_id), db.get(ImportJob, job_id)
        has_concepts = db.scalar(select(Concept.id).where(Concept.kb_id == kb_id).limit(1))
        kb.status = "ready" if has_concepts else "empty"
        job.status = "partial" if failed and has_concepts else "failed" if failed else "completed"
        job.message = (f"导入结束，跳过{skipped}个重复文件。" +
            ("失败文件：" + "、".join(failed) + "；已保存提取进度，重启任务可继续。" if failed else ""))
        db.commit()
        if cleanup and job.status == "completed":
            cleanup_uploads(job)
