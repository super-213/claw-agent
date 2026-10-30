"""Bounded live-model acceptance: five requests, temporary accounts/ledgers only.

Uses configured model unchanged. Intent routing is held at general_chat to test
native tool discovery/execution deterministically without a second intent model.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import AsyncMock
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    report = []
    with tempfile.TemporaryDirectory(prefix='activity-live-') as temporary:
        root = Path(temporary)
        for key, value in {'HOME_DATA_DIR': 'home', 'GENERATED_FILES_DIR': 'files', 'CONVERSATION_DIR': 'sessions', 'RUN_DIR': 'runs', 'USER_FILE': 'users.json'}.items():
            os.environ[key] = str(root / value)
        os.environ['HOME_REMINDER_DELIVERY_ENABLED'] = 'false'
        import web_app as w
        from fastapi.testclient import TestClient
        from services.intent_router import IntentRouteResult
        w.config.config['agent_max_steps'] = 10
        w.config.config['agent_max_runtime_seconds'] = 120
        w.intent_router.route = AsyncMock(return_value=IntentRouteResult(action='general_chat', source='bounded-activity-eval'))
        people = [w.user_store.create_user(username='activity-live-' + name, password='Activity-live-123', role='admin' if name == 'a' else 'user') for name in 'abc']
        for identifier, person in zip('ABC', people):
            w.family_members.update(identifier, {'user_id': person['id'], 'display_name': '测试成员' + identifier}, people[0])
        with TestClient(w.app) as client:
            client.cookies.set(w.AUTH_COOKIE_NAME, w.auth_sessions.create(people[0]['id']))
            def ask(question):
                sid = client.post('/api/sessions').json()['id']
                response = client.post('/api/chat', json={'session_id': sid, 'message': question, 'request_id': 'live-' + str(len(report))})
                session = client.get('/api/sessions/' + sid).json()
                calls = [call['function']['name'] for message in session['messages'] for call in message.get('tool_calls', [])]
                blocks = session['messages'][-1].get('ui_blocks', [])
                return response, calls, blocks
            def record(name, passed, calls):
                report.append({'case': name, 'passed': bool(passed), 'tools': calls})
                print(('PASS' if passed else 'FAIL') + ' ' + name + ': ' + ','.join(calls), flush=True)
            poll_id = None
            if len(sys.argv) == 1:
                response, calls, blocks = ask('创建家庭投票并发布到留言板：周末去哪，选项公园、博物馆，参与24小时后截止，保留48小时后自动销毁，结束通知我。')
                polls = w.family_activities.list(people[0], 'poll')
                poll_id = polls[0]['resource']['id'] if polls else None
                record('poll-create', response.status_code == 200 and response.json().get('run_status') == 'completed' and len(polls) == 1 and bool(polls[0]['activity']['expires_at']) and bool(polls[0]['activity']['participation_deadline_at']) and any(b['kind'] == 'poll' for b in blocks) and 'tool_load' in calls, calls)
                response, calls, blocks = ask('创建家庭接龙并发布：周日采购接龙，填写想买的物品，最多3位成员，保留48小时，结束提醒我。')
                relays = w.family_activities.list(people[0], 'relay')
                record('relay-create', response.status_code == 200 and len(relays) == 1 and relays[0]['activity']['capacity'] == 3 and bool(relays[0]['activity']['expires_at']) and any(b['kind'] == 'relay' for b in blocks), calls)
            response, calls, blocks = ask('先拟一个家庭投票草稿：晚餐选择，选项米饭、面条。参与截止时间稍后在卡片中选择，现在不要发布。')
            record('draft', response.status_code == 200 and any(b['kind'] == 'poll' and b['mode'] == 'draft' for b in blocks) and len(w.family_activities.list(people[0], 'poll')) == (1 if poll_id else 0), calls)
            if poll_id:
                response, calls, blocks = ask('把家庭投票 ' + poll_id + ' 的说明改为“带好水杯”，只修改这条原活动，不新建，其他配置不变。')
                row = w.family_activities.get(people[0], 'poll', poll_id)['activity']
                record('poll-update', response.status_code == 200 and row['description'] == '带好水杯' and len(w.family_activities.list(people[0], 'poll')) == 1, calls)
                response, calls, blocks = ask('永久删除家庭投票 ' + poll_id + '，我确定不需要了。')
                record('poll-delete', response.status_code == 200 and not w.family_activities.list(people[0], 'poll'), calls)
    output = ROOT / '.data/validation/family-activities/live-chat-results.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    if len(sys.argv) > 1 and output.exists():
        previous = json.loads(output.read_text())
        changed = {row['case'] for row in report}
        report = [row for row in previous if row['case'] not in changed] + report
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f'{sum(row["passed"] for row in report)}/{len(report)} checks passed; {output}')
    return 0 if len(report) == 5 and all(row['passed'] for row in report) else 1


if __name__ == '__main__': sys.exit(main())
