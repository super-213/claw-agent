"""014 isolated real browser fixture: synthetic accounts, no production writes."""
import os
from pathlib import Path
import sys
import tempfile
from datetime import datetime, timedelta
import time
from zoneinfo import ZoneInfo
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
root = Path(tempfile.mkdtemp(prefix='board014-'))
for key, value in {'HOME_DATA_DIR': 'home', 'GENERATED_FILES_DIR': 'files', 'CONVERSATION_DIR': 'sessions',
                   'RUN_DIR': 'runs', 'USER_FILE': 'users.json'}.items():
    os.environ[key] = str(root / value)
os.environ['HOME_REMINDER_DELIVERY_ENABLED'] = 'false'
import web_app as w
from agent_runtime import AgentModelResponse, ToolCall
import uvicorn
clock = [datetime(2026, 10, 27, 12, tzinfo=ZoneInfo('Asia/Shanghai'))]
ticking = [False]
clock_started = [time.monotonic()]
def fixture_now():
    return clock[0] + timedelta(seconds=time.monotonic() - clock_started[0]) if ticking[0] else clock[0]
w.family_tasks.clock = w.family_board.clock = w.family_activities.clock = fixture_now
w.home_service._now = lambda: clock[0]
people = [w.user_store.create_user(username='board014' + suffix, password='Board014-test', display_name=name, role='admin' if not suffix else 'user') for suffix, name in [('', '小林'), ('b', '小陈'), ('c', '小周')]]
for member, person in zip('ABC', people):
    w.family_members.update(member, {'user_id': person['id'], 'display_name': person['display_name']}, people[0])


class FixtureModel:
    model = 'board014-native-stub'
    context_window = 32768
    def __init__(self): self.turn = 0
    async def __aenter__(self): return self
    async def __aexit__(self, *_): pass
    async def achat_with_tools(self, messages, schemas):
        self.turn += 1
        if self.turn != 1: return AgentModelResponse(content='处理结果以工具回执为准。')
        return AgentModelResponse(tool_calls=[ToolCall('fixture-board', 'family_board_post_create', {'data': {
            'title': 'Agent 的留言', 'content_blocks': [{'type': 'text', 'text': '照片已经整理好，周末一起看看。'}]}})])
    async def astream_with_tools(self, messages, schemas):
        yield {'type': 'done', 'response': await self.achat_with_tools(messages, schemas)}
w._new_llm_client = FixtureModel

# Delay only isolated fixture uploads to verify local previews before the server reply.
if os.getenv('BOARD_CARD_READ_DELAY'):
    original_get = w.family_board.get
    def delayed_get(*args, **kwargs):
        time.sleep(float(os.environ['BOARD_CARD_READ_DELAY']))
        return original_get(*args, **kwargs)
    w.family_board.get = delayed_get

if os.getenv('BOARD_UPLOAD_DELAY'):
    original_upload = w.family_board.upload
    def delayed_upload(user, data):
        time.sleep(float(os.environ['BOARD_UPLOAD_DELAY']))
        return original_upload(user, data)
    w.family_board.upload = delayed_upload



@w.app.post('/api/__test/clock')
def change_clock(payload: dict):
    clock[0] = datetime.fromisoformat(payload['now']).astimezone(ZoneInfo('Asia/Shanghai'))
    ticking[0] = payload.get('ticking', False)
    clock_started[0] = time.monotonic()
    return {'now': clock[0].isoformat()}


uvicorn.run(w.app, host='127.0.0.1', port=int(os.environ['BOARD014_API_PORT']), log_level='warning')
