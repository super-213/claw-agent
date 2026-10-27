"""Live configured-model board smoke tests in isolated temporary storage.

Uses normal model quota, never production members, notes or chat history.
"""
import json
from io import BytesIO
from PIL import Image
import os
from pathlib import Path
import sys
import tempfile
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    report = []
    with tempfile.TemporaryDirectory(prefix='board-live-') as temporary:
        root = Path(temporary)
        for key, value in {'HOME_DATA_DIR': 'home', 'GENERATED_FILES_DIR': 'files', 'CONVERSATION_DIR': 'sessions',
                           'RUN_DIR': 'runs', 'USER_FILE': 'users.json'}.items():
            os.environ[key] = str(root / value)
        os.environ['HOME_REMINDER_DELIVERY_ENABLED'] = 'false'
        import web_app as w
        from fastapi.testclient import TestClient
        users = [w.user_store.create_user(username='board-live-' + name, password='Board-live-123', role='admin' if name == 'a' else 'user') for name in 'abc']
        for identifier, user, name in zip('ABC', users, ['验收作者', '小陈', '小周']):
            w.family_members.update(identifier, {'user_id': user['id'], 'display_name': name}, users[0])
        cases = [
            ('@ 小陈 帮我发一张便笺：晚饭在冰箱第二层，长期保留。', 'saved', ['B'], 'permanent'),
            ('@ 小陈 @ 小周 帮我发一张便笺：周末一起整理照片，保留24小时。', 'saved', ['B', 'C'], 'until'),
            ('@ 所有人 帮我发张便笺：周六一起吃饭，长期保留。', 'saved', [], 'permanent'),
            ('帮我先写一张便笺草稿：回来记得关窗，限时保留，接收人和截止时间我在卡片里选。', 'draft', [], 'until'),
            ('@ 小陈 把这次上传的图片放进便笺发给小陈，配文“今天拍的照片”，长期保留。', 'saved', ['B'], 'permanent'),
        ]
        with TestClient(w.app) as client:
            client.cookies.set(w.AUTH_COOKIE_NAME, w.auth_sessions.create(users[0]['id']))
            for index, (question, mode, recipients, retention) in enumerate(cases):
                if len(sys.argv) > 1 and index + 1 != int(sys.argv[1]): continue
                session_id = client.post('/api/sessions').json()['id']
                payload = {'session_id': session_id, 'message': question, 'request_id': f'board-live-{index}'}
                if index == 4:
                    photo = BytesIO()
                    Image.new('RGB', (80, 60), '#baa785').save(photo, 'PNG')
                    uploaded = client.post('/api/chat/uploads', files={'files': ('picture.png', photo.getvalue(), 'image/png')}).json()['media']
                    payload['images'] = uploaded
                response = client.post('/api/chat', json=payload)
                messages = client.get('/api/sessions/' + session_id).json()['messages']
                calls = [call['function']['name'] for message in messages for call in message.get('tool_calls', [])]
                blocks = messages[-1].get('ui_blocks') or []
                valid = response.status_code == 200 and response.json().get('run_status') == 'completed' and len(blocks) == 1 and blocks[0]['kind'] == 'board_post'
                post = {}
                if blocks:
                    block = blocks[0]
                    card_response = client.get('/api/home/board/' + ('drafts/' if block['mode'] == 'draft' else 'posts/') + block['resource']['id'], params={'session_id': session_id})
                    if card_response.status_code == 200:
                        card = card_response.json()
                        post = card['post']
                        valid = valid and card['mode'] == mode and post['recipient_ids'] == recipients and post['retention_mode'] == retention
                        if index == 2: valid = valid and post['audience_mode'] == 'household'
                        if index == 1: valid = valid and post['expires_at'] is not None
                        if index == 4: valid = valid and any(block['type'] == 'image' for block in post['content_blocks'])
                    else: valid = False
                report.append({'question': question, 'passed': bool(valid), 'tools': calls, 'post': post, 'answer': messages[-1].get('content', ''), 'tool_calls': [call for message in messages for call in message.get('tool_calls', [])]})
                print(f"{'PASS' if valid else 'FAIL'} board case {index + 1}: {','.join(calls)}", flush=True)
    output = ROOT / '.data/validation/board/live-chat-results.json'
    if len(sys.argv) > 1 and output.exists():
        previous = json.loads(output.read_text())
        changed = {row['question'] for row in report}
        report = [row for row in previous if row['question'] not in changed] + report
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Board model checks: {sum(row['passed'] for row in report)}/{len(report)}; {output}")
    return 0 if all(row['passed'] for row in report) else 1


if __name__ == '__main__': sys.exit(main())
