"""Live-model smoke test of natural-language task creation in temporary storage.

Uses the configured model and its normal API quota. Does not touch real tasks.
"""
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    report = []
    with tempfile.TemporaryDirectory(prefix='task-chat-live-') as temporary:
        root = Path(temporary)
        for key, value in {'HOME_DATA_DIR': 'home', 'GENERATED_FILES_DIR': 'files', 'CONVERSATION_DIR': 'sessions',
                           'RUN_DIR': 'runs', 'USER_FILE': 'users.json'}.items():
            os.environ[key] = str(root / value)
        os.environ['HOME_REMINDER_DELIVERY_ENABLED'] = 'false'
        import web_app as w
        from fastapi.testclient import TestClient

        user = w.user_store.create_user(username='task-live-check', password='Task-check-123', role='admin')
        w.family_members.update('A', {'user_id': user['id'], 'display_name': '验收成员'}, user)
        now = w.family_tasks.now()
        w.family_tasks.clock = lambda: now
        cases = [
            ('帮我记一下 明天这个时候叫我去上海', 'personal', 'timed'),
            ('帮我添加一条备忘，买牛奶', 'personal', 'undated'),
            ('给全家创建日程，明天晚上七点一起大扫除', 'household', 'timed'),
            ('给全家记一条备忘，买垃圾袋', 'household', 'undated'),
        ]
        with TestClient(w.app) as client:
            client.cookies.set(w.AUTH_COOKIE_NAME, w.auth_sessions.create(user['id']))
            for index, (question, space, temporal) in enumerate(cases):
                session_id = client.post('/api/sessions').json()['id']
                response = client.post('/api/chat', json={
                    'session_id': session_id, 'message': question, 'request_id': f'live-task-{index}'})
                result = response.json()
                messages = client.get('/api/sessions/' + session_id).json()['messages']
                calls = [call['function']['name'] for message in messages for call in message.get('tool_calls', [])]
                tasks = [task for task in w.family_tasks.store.snapshot()['tasks'].values()
                         if task.get('source', {}).get('session_id') == session_id]
                valid = (response.status_code == 200 and result.get('run_status') == 'completed'
                         and len(tasks) == 1 and tasks[0]['space_type'] == space and tasks[0]['temporal_type'] == temporal)
                blocks = messages[-1].get('ui_blocks') or []
                valid = valid and len(blocks) == 1 and blocks[0].get('kind') == 'task'
                if blocks:
                    resource = blocks[0]['resource']
                    card = client.get('/api/home/tasks/' + resource['id'] + '/card', params={
                        'instance_id': resource.get('instance_id'), 'session_id': session_id})
                    valid = valid and card.status_code == 200 and card.json()['task']['id'] == tasks[0]['id']
                if temporal == 'timed' and tasks:
                    valid = valid and tasks[0]['due_date'] == (now.date() + timedelta(days=1)).isoformat()
                    if index == 0:
                        timestamp = datetime.fromisoformat(tasks[0]['due_at']) if tasks[0].get('due_at') else None
                        valid = valid and timestamp is not None and abs((timestamp - (now + timedelta(days=1))).total_seconds()) < 120
                    calendar = client.get('/api/home/tasks', params={'view': 'visible', 'temporal_type': 'timed',
                        'due_from': tasks[0]['due_date'], 'due_to': tasks[0]['due_date']}).json()
                    valid = valid and any(row['task']['id'] == tasks[0]['id'] for row in calendar['items'])
                row = {'question': question, 'passed': bool(valid), 'tools': calls,
                       'answer': messages[-1].get('content', ''), 'tasks': [
                           {key: task.get(key) for key in ('title', 'space_type', 'temporal_type', 'due_date', 'due_at')} for task in tasks]}
                report.append(row)
                print(f"{'PASS' if valid else 'FAIL'} {space}/{temporal}: {','.join(calls)}", flush=True)
    output = ROOT / '.data/validation/tasks/live-chat-results.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Natural task chat: {sum(row['passed'] for row in report)}/{len(report)}; {output}")
    return 0 if all(row['passed'] for row in report) else 1


if __name__ == '__main__':
    sys.exit(main())
