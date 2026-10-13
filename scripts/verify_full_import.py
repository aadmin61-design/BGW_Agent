"""核对完整原文与线上向量；显式--model才创建并清理独立问答测试账号。"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import secrets
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from sqlalchemy import select, func
from backend.database import session_factory
from backend.models import User, KnowledgeBase, Document, Chunk, Concept, ImportCheckpoint, ImportPiece, DailyItem
from backend.ingestion import parse_document
from backend.security import passwords, token
from backend.main import snapshot_of, today


def verify(kb_id, path, model=False):
    factory = session_factory()
    pieces = parse_document(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with factory() as db:
        kb = db.get(KnowledgeBase, kb_id)
        assert kb and kb.status == 'ready', 'knowledge_not_ready'
        doc = db.scalar(select(Document).where(Document.kb_id == kb_id, Document.digest == digest))
        assert doc, 'original_hash_mismatch'
        chunks = list(db.scalars(select(Chunk).where(Chunk.doc_id == doc.id)))
        assert len(chunks) == len(pieces), 'chunk_count_mismatch'
        by_source = {chunk.source: chunk for chunk in chunks}
        assert len(by_source) == len(pieces), 'duplicate_chunk_source'
        assert all(source in by_source and by_source[source].text == text for text, source in pieces), 'original_text_mismatch'
        checkpoint = db.get(ImportCheckpoint, doc.id)
        assert checkpoint and checkpoint.completed
        assert checkpoint.processed_chunks == checkpoint.vectorized_chunks == len(pieces)
        assert db.scalar(select(func.count()).select_from(ImportPiece).where(ImportPiece.checkpoint_id == doc.id)) == 0
        concepts = list(db.scalars(select(Concept).where(Concept.kb_id == kb_id)))
        assert concepts, 'no_concepts'
        ordered = sorted(concepts, key=lambda c: (c.depth, c.title, c.id))
        seen = set()
        for concept in ordered:
            assert set(concept.prerequisites).issubset(seen), 'invalid_dependency_graph'
            assert 1 <= concept.depth <= 5 and concept.chunk_id in {c.id for c in chunks}
            seen.add(concept.id)
        administrator = db.scalar(select(User).where(User.is_admin.is_(True)))
        report = {'kb_id': kb_id, 'sha256': digest, 'original_bytes': path.stat().st_size,
                  'chunks': len(chunks), 'concepts': len(concepts), 'text_matches_original': True,
                  'checkpoint_complete': True, 'dependency_graph': 'passed',
                  'categories': dict(Counter(c.category for c in concepts)),
                  'depths': dict(Counter(c.depth for c in concepts))}
    with httpx.Client(base_url='http://127.0.0.1:8001', trust_env=False, timeout=30) as client:
        # 只在内存中签发会话，不读取或输出原用户密码、JWT及文档正文。
        client.cookies.set('bgw_session', token(administrator))
        response = client.get(f'/api/admin/knowledge-bases/{kb_id}/integrity')
        assert response.status_code == 200, f'integrity_http_{response.status_code}'
        report['vector_integrity'] = response.json()
        assert response.json()['vectors']['ok'], 'vector_integrity_failed'
        if model:
            probe_id = None
            try:
                with factory() as db:
                    probe = User(username='full_probe_' + secrets.token_hex(6),
                                 password_hash=passwords.hash(secrets.token_urlsafe(32)))
                    db.add(probe); db.flush(); probe_id = probe.id
                    # 从文档前、中、后有知识点的片段各取一道，不影响原用户今日计划。
                    rank = {by_source[source].id: i for i, (_, source) in enumerate(pieces)}
                    sorted_concepts = sorted(concepts, key=lambda c: (rank[c.chunk_id], c.id))
                    selected = [sorted_concepts[i] for i in (0, len(sorted_concepts)//2, len(sorted_concepts)-1)]
                    items = []
                    for i, concept in enumerate(selected):
                        item = DailyItem(user_id=probe.id, kb_id=kb_id, concept_id=concept.id,
                                         day=today(), kind='lesson', ordinal=i, snapshot=snapshot_of(db, concept))
                        db.add(item); items.append(item)
                    db.commit()
                client.cookies.clear(); client.cookies.set('bgw_session', token(probe))
                answers = []
                for item in items:
                    response = client.post(f'/api/items/{item.id}/conversation',
                        json={'message': '围绕当前知识点，简短说明核心原理，并引用知识库来源。'}, timeout=150)
                    assert response.status_code == 200, f'tutor_http_{response.status_code}'
                    messages = response.json()['messages']
                    assert [m['role'] for m in messages] == ['user', 'assistant'], 'message_order'
                    reply = messages[-1]
                    assert reply['content'].strip() and reply['sources'], 'missing_reply_or_source'
                    assert all(s['source'].startswith(path.name + ' · ') for s in reply['sources']), 'cross_kb_source'
                    answers.append({'http': 200, 'sources': len(reply['sources']), 'characters': len(reply['content'])})
                report['tutor_probes'] = answers
            finally:
                if probe_id:
                    with factory() as db:
                        # 精确删除本次测试ID；外键级联清理其计划和消息。
                        probe = db.get(User, probe_id)
                        if probe:
                            db.delete(probe); db.commit()
                    with factory() as db:
                        assert db.get(User, probe_id) is None
                    report['temporary_probe_cleanup'] = 'passed'
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--kb-id', required=True)
    parser.add_argument('--path', required=True, type=Path)
    parser.add_argument('--model', action='store_true')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    try:
        report = verify(args.kb_id, args.path, args.model)
        if args.report:
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False))
    except Exception as error:
        print(json.dumps({'verification': 'failed', 'type': type(error).__name__,
                          'stage': str(error) if isinstance(error, AssertionError) else None}))
        sys.exit(1)
