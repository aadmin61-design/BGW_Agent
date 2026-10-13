"""通过临时HTTPS入口验证完整业务；仅创建并清理本次独立测试账号。"""
import argparse
import json
from pathlib import Path
import secrets
import sys
import time
from urllib.parse import urlsplit
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from sqlalchemy import select
from backend.database import session_factory
from backend.models import User, KnowledgeBase, Concept, DailyItem
from backend.main import snapshot_of, today


def verify(url, report_path):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname.endswith('.trycloudflare.com') or parsed.username or parsed.port:
        raise ValueError('只允许本次临时Cloudflare HTTPS入口')
    factory = session_factory()
    credentials = {'username': 'tunnel_probe_' + secrets.token_hex(6), 'password': secrets.token_urlsafe(24)}
    report = {'url': url, 'status': 'running', 'phases': []}
    def save():
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    def checked(response, expected, phase):
        assert response.status_code == expected, f'{phase}_http_{response.status_code}'
        report['phases'].append(phase); save()
    probe_id = None
    save()
    try:
        with httpx.Client(base_url=url, trust_env=False, timeout=25, headers={'Origin': url}) as client:
            checked(client.get('/api/health'), 200, 'https_health')
            checked(client.get('/'), 200, 'homepage')
            response = client.post('/api/auth/register', json=credentials)
            checked(response, 201, 'registration')
            probe_id = response.json()['id']
            cookie = response.headers.get('set-cookie', '').lower()
            assert 'secure' in cookie and 'httponly' in cookie, 'cookie_protection'
            report['secure_cookie'] = True
            checked(client.get('/api/auth/me'), 200, 'authenticated_session')
            checked(client.post('/api/auth/logout'), 200, 'logout')
            checked(client.post('/api/auth/login', json=credentials), 200, 'password_login')
            checked(client.get('/api/dashboard'), 200, 'dashboard')
            response = client.post('/api/plans/lesson', json={})
            checked(response, 200, 'daily_learning')
            assert len(response.json()['items']) == 10, 'lesson_count'
            with factory() as db:
                # 测试完整知识库已发布内容，不操作原用户的学习计划。
                kb = db.scalar(select(KnowledgeBase).where(KnowledgeBase.status == 'ready',
                    KnowledgeBase.name.like('%10万字总结%')))
                assert kb is not None, 'published_knowledge_missing'
                concept = db.scalar(select(Concept).where(Concept.kb_id == kb.id, Concept.depth == 1))
                item = DailyItem(user_id=probe_id, kb_id=kb.id, concept_id=concept.id, day=today(), kind='lesson',
                    ordinal=10, snapshot=snapshot_of(db, concept))
                db.add(item); db.commit()
                item_id, title = item.id, concept.title
            started = time.monotonic()
            response = client.post(f'/api/items/{item_id}/conversation', timeout=110,
                json={'message': f'关于{title}，用不超过三句话解释核心原理，引用知识库资料。'})
            checked(response, 200, 'tutor')
            messages = response.json()['messages']
            assert [m['role'] for m in messages] == ['user', 'assistant'], 'message_order'
            answer = messages[-1]
            assert answer['content'].strip() and answer['sources'], 'grounded_reply'
            assert all(s['source'].startswith('10万字总结.docx · ') for s in answer['sources']), 'knowledge_isolation'
            report['tutor'] = {'http': 200, 'seconds': round(time.monotonic()-started, 2),
                'sources': len(answer['sources']), 'characters': len(answer['content'])}
            report['status'] = 'passed'
    except Exception as error:
        # 不记录请求头、响应正文、随机密码或JWT。
        report.update(status='failed', error_type=type(error).__name__,
            stage=str(error) if isinstance(error, AssertionError) else None)
    finally:
        with factory() as db:
            # 网络超时也可能已创建账号，只按本次唯一名称和ID精确清理。
            probe = db.scalar(select(User).where(User.username == credentials['username']))
            if probe and (probe_id is None or probe.id == probe_id):
                db.delete(probe); db.commit()
        with factory() as db:
            assert db.scalar(select(User.id).where(User.username == credentials['username'])) is None
        report['temporary_probe_cleanup'] = 'passed'
        save()
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    verify(args.url.rstrip('/'), args.report)
