"""013 isolated browser fixture. No real users, tasks, runs or model calls."""
import os
from pathlib import Path
import sys
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
root = Path(tempfile.mkdtemp(prefix='cards013-'))
for key, value in {'HOME_DATA_DIR': 'home', 'GENERATED_FILES_DIR': 'files', 'CONVERSATION_DIR': 'sessions',
                   'RUN_DIR': 'runs', 'USER_FILE': 'users.json'}.items():
    os.environ[key] = str(root / value)
os.environ['HOME_REMINDER_DELIVERY_ENABLED'] = 'false'

import web_app as w
from agent_runtime import AgentModelResponse, ToolCall
import uvicorn

clock = [datetime(2026, 10, 27, 12, tzinfo=ZoneInfo('Asia/Shanghai'))]
w.family_tasks.clock = lambda: clock[0]
w.home_service._now = lambda: clock[0]
alice = w.user_store.create_user(username='cards013', password='Cards013-test', display_name='小林', role='admin')
bob = w.user_store.create_user(username='cards013b', password='Cards013-test', display_name='小陈', role='user')
for member, person in [('A', alice), ('B', bob)]:
    w.family_members.update(member, {'user_id': person['id'], 'display_name': person['display_name']}, alice)


class FixtureModel:
    model = 'cards013-native-stub'
    context_window = 32768
    def __init__(self): self.turn = 0
    async def __aenter__(self): return self
    async def __aexit__(self, *_): pass
    async def achat_with_tools(self, messages, schemas):
        self.turn += 1
        if self.turn != 1:
            return AgentModelResponse(content='结果以工具回执为准。')
        raw = next(m['content'] for m in reversed(messages) if m['role'] == 'user')
        if '备忘' in raw:
            name, item = 'family_undated_memo_create', {'title': '买牛奶'}
        else:
            name, item = 'family_timed_memo_create', {'title': '去上海'}
            if '草稿' not in raw:
                item['due_at'] = '2026-10-28T17:34:00+08:00'
        return AgentModelResponse(tool_calls=[ToolCall('fixture-create', name, {'items': [item]})])
    async def astream_with_tools(self, messages, schemas):
        yield {'type': 'done', 'response': await self.achat_with_tools(messages, schemas)}


w._new_llm_client = FixtureModel


@w.app.post('/api/__test/clock')
def change_clock(payload: dict):
    clock[0] = datetime.fromisoformat(payload['now']).astimezone(ZoneInfo('Asia/Shanghai'))
    return {'now': clock[0].isoformat()}


uvicorn.run(w.app, host='127.0.0.1', port=int(os.environ['CARDS013_API_PORT']), log_level='warning')
