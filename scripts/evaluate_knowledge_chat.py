"""Live native-tool chat smoke test with isolated accounts and synthetic files.

Uses the configured model. All accounts, library entries and runs are temporary.
"""
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    with tempfile.TemporaryDirectory(prefix='knowledge-live-chat-') as temporary:
        root = Path(temporary)
        for key, value in {'HOME_DATA_DIR': 'home', 'GENERATED_FILES_DIR': 'files', 'CONVERSATION_DIR': 'sessions',
                           'RUN_DIR': 'runs', 'USER_FILE': 'users.json'}.items():
            os.environ[key] = str(root / value)
        os.environ['HOME_REMINDER_DELIVERY_ENABLED'] = 'false'
        import web_app as w
        from fastapi.testclient import TestClient
        user = w.user_store.create_user(username='live-knowledge-eval', password='Live-eval-123', role='admin')
        report = []
        with TestClient(w.app) as client:
            client.cookies.set(w.AUTH_COOKIE_NAME, w.auth_sessions.create(user['id']))

            def chat(question, *, attachments=None, expected=(), tool=None):
                session = client.post('/api/sessions').json()['id']
                response = client.post('/api/chat', json={'session_id': session, 'message': question, 'attachments': attachments or []})
                if response.status_code != 200:
                    raise RuntimeError(f'chat_http_{response.status_code}')
                result = response.json()
                messages = client.get('/api/sessions/' + session).json()['messages']
                answers = [m.get('content', '') for m in messages if m['role'] == 'assistant' and not m.get('tool_calls')]
                answer = answers[-1] if answers else ''
                names = [call['function']['name'] for m in messages for call in m.get('tool_calls', [])]
                passed = result.get('run_status') == 'completed' and all(word in answer for word in expected) and (not tool or tool in names)
                report.extend([f"## {'通过' if passed else '需检查'} {question}", '', f"工具：{', '.join(names)}", '', answer, ''])
                print(f"{'PASS' if passed else 'FAIL'} {question} tools={','.join(names)}", flush=True)
                return passed

            media = client.post('/api/chat/uploads', files=[('files', ('设备说明书.txt', '客厅空调型号 LIVE-771。清洗滤网时先断电，再用清水冲洗。'.encode(), 'text/plain'))]).json()['media']
            outcomes = [chat('请保存这份说明书，名称为客厅空调说明书，关联客厅空调。', attachments=media, tool='knowledge_document_save')]
            outcomes.append(chat('之前保存的客厅空调说明书，型号是什么？请给出处。', expected=('LIVE-771', '/api/knowledge/'), tool='knowledge_search'))
            outcomes.append(chat('帮我记住：备用钥匙在玄关第二层抽屉。', tool='knowledge_record_save'))
            outcomes.append(chat('把备用钥匙的位置改成书房抽屉。', tool='knowledge_update'))
            outcomes.append(chat('之前记住的备用钥匙放在哪里？请查最新记录。', expected=('书房', '/api/knowledge/'), tool='knowledge_search'))
        output = ROOT / '.data/validation/knowledge/live-chat-evaluation.md'
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text('# 011 真实模型原生工具对话验收\n\n使用临时账号与合成资料，逐题新建会话。来源链接在临时数据清理后失效。\n\n' + '\n'.join(report))
        print(f'Live native-tool chat: {sum(outcomes)}/{len(outcomes)}. Report: {output}')
        return 0 if all(outcomes) else 1


if __name__ == '__main__':
    sys.exit(main())
