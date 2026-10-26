from copy import deepcopy
from datetime import datetime
import json
from zoneinfo import ZoneInfo

import pytest

from agent_runtime import AgentModelResponse, ToolCall
from services.task_commands import infer_task_invocation, normalize_invocation
from services.task_chat import guard_task_answer
from test_family_task_api import api, FakeLLM  # noqa: F401
import web_app


@pytest.mark.parametrize('text,space,temporal', [
    ('帮我记一下 明天这个时候叫我去上海', 'personal', 'timed'),
    ('添加备忘，买牛奶', 'personal', 'undated'),
    ('给全家创建日程，周六大扫除', 'household', 'timed'),
    ('给全家记一条备忘，买垃圾袋', 'household', 'undated'),
    ('创建家庭备忘，记得买洗衣液', 'household', 'undated'),
    ('添加个人备忘，给全家买菜', 'personal', 'undated'),
    ('安排今晚八点去取快递', 'personal', 'timed'),
    ('创建日程，去取快递', 'personal', 'timed'),
    ('帮我记一下买牛奶', 'personal', 'undated'),
    ('不要忘了明天提醒我出门', 'personal', 'timed'),
])
def test_natural_creation_selection(text, space, temporal):
    value = infer_task_invocation(text)
    assert (value['space_type'], value['temporal_type']) == (space, temporal)
    assert value['mentions'] == []


@pytest.mark.parametrize('text', [
    '不要创建家庭日程', '不用提醒我明天出门', '如何创建日程？',
    '如果明天要出门，怎么安排日程？', '查询明天日程', '我的日程保存成功了吗？',
    '帮我记住：备用钥匙在玄关抽屉', '帮我记一下昨天已经换过滤芯',
    '`创建家庭日程`', '“明天提醒我”是什么意思？',
])
def test_non_creation_text_does_not_select_task(text):
    assert infer_task_invocation(text) is None


@pytest.mark.parametrize('stream', [False, True])
@pytest.mark.parametrize('message,space,temporal', [
    ('帮我记一下 明天这个时候叫我去上海', 'personal', 'timed'),
    ('添加备忘，买牛奶', 'personal', 'undated'),
    ('给全家创建日程，明天大扫除', 'household', 'timed'),
    ('给全家记一条备忘，买垃圾袋', 'household', 'undated'),
])
def test_natural_chat_persists_four_types_and_calendar_reads_them(api, monkeypatch, stream, message, space, temporal):
    clients, service, users, clock = api
    clock[0] = datetime(2026, 10, 26, 17, 34, tzinfo=ZoneInfo('Asia/Shanghai'))
    session = clients[0].post('/api/sessions').json()
    item = {'title': '自然语言创建验证'}
    if temporal == 'timed':
        # Reproduce the original model call: due_at without due_date.
        item['due_at'] = '2026-10-27T17:34:00+08:00'
    model = FakeLLM([ToolCall('create', f'family_{temporal}_memo_create', {'items': [item]})])
    monkeypatch.setattr(web_app, '_new_llm_client', lambda: model)
    body = {'session_id': session['id'], 'message': message, 'request_id': 'natural'}
    response = clients[0].post('/api/chat/stream' if stream else '/api/chat', json=body)
    assert response.status_code == 200, response.text
    if stream:
        events = [json.loads(line) for line in response.text.splitlines()]
        assert any(e['type'] == 'task_changed' for e in events)
        messages = events[-1]['messages']
    else:
        messages = response.json()['messages']
    assert '已保存以下事项' in messages[-1]['content']
    rows = clients[0].get('/api/home/tasks?view=visible').json()['items']
    assert len(rows) == 1
    task = rows[0]['task']
    assert (task['space_type'], task['temporal_type']) == (space, temporal)
    assert clients[1].get('/api/home/tasks?view=visible').json()['total'] == (1 if space == 'household' else 0)
    if temporal == 'timed':
        calendar = clients[0].get('/api/home/tasks?view=visible&status=open&actionable=true&temporal_type=timed&due_from=2026-10-27&due_to=2026-10-27').json()
        assert calendar['items'][0]['occurrence']['due_date'] == '2026-10-27'
        assert task['due_date'] == '2026-10-27'
        assert task['due_at'] == item['due_at']
    # Retrying a request must not create duplicates.
    model.turn = 0
    assert clients[0].post('/api/chat/stream' if stream else '/api/chat', json=body).status_code == 200
    assert len(service.store.snapshot()['tasks']) == 1
    assert service.members.home._send_web_push_to_recipients.call_count == 0


class ScriptedLLM(FakeLLM):
    def __init__(self, responses):
        super().__init__([])
        self.responses = responses
        self.requests = []

    async def achat_with_tools(self, messages, schemas):
        self.requests.append(deepcopy(messages))
        response = self.responses[min(self.turn, len(self.responses) - 1)]
        self.turn += 1
        return deepcopy(response)

    async def astream_with_tools(self, messages, schemas):
        response = await self.achat_with_tools(messages, schemas)
        yield {'type': 'content_delta', 'delta': response.content}
        yield {'type': 'done', 'response': response}


@pytest.mark.parametrize('stream', [False, True])
def test_false_success_is_retried_and_only_real_receipt_is_published(api, monkeypatch, stream):
    clients, service, _, _ = api
    session = clients[0].post('/api/sessions').json()
    model = ScriptedLLM([
        AgentModelResponse(content='已成功创建日程：虚构时间，到时自动通知你'),
        AgentModelResponse(content='已创建成功！', tool_calls=[ToolCall('create', 'family_timed_memo_create',
            {'items': [{'title': '去上海', 'due_at': '2026-10-27T17:34:00+08:00'}]})]),
        AgentModelResponse(content='已创建在2099年，会自动打电话提醒你'),
    ])
    monkeypatch.setattr(web_app, '_new_llm_client', lambda: model)
    response = clients[0].post('/api/chat/stream' if stream else '/api/chat', json={
        'session_id': session['id'], 'message': '帮我记一下 明天这个时候叫我去上海'})
    assert response.status_code == 200
    assert len(service.store.snapshot()['tasks']) == 1
    assert model.turn == 3
    assert any('本轮没有成功' in m.get('content', '') for m in model.requests[1] if m['role'] == 'system')
    assert '虚构时间' not in response.text and '2099' not in response.text and '自动打电话' not in response.text
    saved = web_app.store.load_session(session['id'])['messages']
    assert saved[-1]['content'].startswith('已保存以下事项')
    assert '2026-10-27 17:34' in saved[-1]['content']


def test_uncooperative_model_cannot_publish_false_success(api, monkeypatch):
    clients, service, _, _ = api
    session = clients[0].post('/api/sessions').json()
    model = ScriptedLLM([AgentModelResponse(content='已成功创建日程')])
    monkeypatch.setattr(web_app, '_new_llm_client', lambda: model)
    response = clients[0].post('/api/chat', json={'session_id': session['id'], 'message': '创建日程，明天去上海'})
    assert response.status_code == 200
    assert model.turn == 2
    assert not service.store.snapshot()['tasks']
    assert '尚未保存' in response.json()['messages'][-1]['content']


def test_large_batch_receipt_and_refresh_survive_truncated_tool_output(api, monkeypatch):
    clients, service, _, _ = api
    session = clients[0].post('/api/sessions').json()
    monkeypatch.setitem(web_app.config.config, 'tool_output_max_chars', 1000)
    items = [{'title': f'批量条目{i:02d}'} for i in range(30)]
    model = FakeLLM([ToolCall('batch', 'family_undated_memo_create', {'items': items})])
    monkeypatch.setattr(web_app, '_new_llm_client', lambda: model)
    response = clients[0].post('/api/chat/stream', json={'session_id': session['id'], 'message': '创建备忘，批量保存这些条目'})
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    assert any(event['type'] == 'task_changed' for event in events)
    assert len(service.store.snapshot()['tasks']) == 30
    answer = events[-1]['messages'][-1]['content']
    assert answer.startswith('已保存以下事项')
    assert all(item['title'] in answer for item in items)


def test_successful_creation_still_has_a_receipt_when_model_final_is_empty(api, monkeypatch):
    clients, service, _, _ = api
    session = clients[0].post('/api/sessions').json()
    model = ScriptedLLM([
        AgentModelResponse(tool_calls=[ToolCall('save', 'family_undated_memo_create', {'items': [{'title': '买牛奶'}]})]),
        AgentModelResponse(content=''),
    ])
    monkeypatch.setattr(web_app, '_new_llm_client', lambda: model)
    response = clients[0].post('/api/chat', json={'session_id': session['id'], 'message': '添加备忘，买牛奶'})
    assert response.json()['run_status'] == 'completed'
    assert '已保存以下事项' in response.json()['messages'][-1]['content']
    assert len(service.store.snapshot()['tasks']) == 1


@pytest.mark.parametrize('confirmation', ['保存', '确定', '/ 日程', '/ 日程 去上海', '就提醒我自己'])
def test_confirmation_resumes_draft_with_original_timestamp(api, monkeypatch, confirmation):
    clients, service, users, clock = api
    session = clients[0].post('/api/sessions').json()
    source = session['active_node_id']
    key = json.dumps([session['id'], 'main', service.members.actor(users[0])])
    original = {'title': '去上海', 'due_at': '2026-10-27T17:34:00+08:00'}
    with service.store.transaction() as doc:
        doc['drafts'][key] = {'items': [original], 'user_id': users[0]['id'], 'user_message_id': source,
            'expires_at': '2026-10-23T13:00:00+08:00'}
    # Deliberately drift the model time: the durable draft remains authoritative.
    model = FakeLLM([ToolCall('save', 'family_timed_memo_create', {'items': [{'title': '错误内容', 'due_date': '2027-01-01'}]})])
    monkeypatch.setattr(web_app, '_new_llm_client', lambda: model)
    response = clients[0].post('/api/chat', json={'session_id': session['id'], 'message': confirmation})
    assert response.status_code == 200, response.text
    tasks = list(service.store.snapshot()['tasks'].values())
    assert len(tasks) == 1 and tasks[0]['title'] == original['title']
    assert tasks[0]['due_at'] == original['due_at']
    assert key not in service.store.snapshot()['drafts']


def test_failure_cannot_be_rendered_as_success_and_draft_remains(api, monkeypatch):
    clients, service, _, _ = api
    session = clients[0].post('/api/sessions').json()
    model = ScriptedLLM([
        AgentModelResponse(tool_calls=[ToolCall('create', 'family_timed_memo_create', {'items': [{'title': '去上海'}]})]),
        AgentModelResponse(content='已成功创建日程！'),
    ])
    monkeypatch.setattr(web_app, '_new_llm_client', lambda: model)
    response = clients[0].post('/api/chat', json={'session_id': session['id'], 'message': '创建日程，去上海'})
    assert '日程需要日期' in response.json()['messages'][-1]['content']
    assert '尚未保存' in response.json()['messages'][-1]['content']
    doc = service.store.snapshot()
    assert not doc['tasks'] and doc['drafts']


def test_missing_date_can_be_supplied_without_a_slash_tag(api, monkeypatch):
    clients, service, _, _ = api
    session = clients[0].post('/api/sessions').json()
    first = FakeLLM([ToolCall('draft', 'family_timed_memo_create', {'items': [{'title': '去上海'}]})])
    monkeypatch.setattr(web_app, '_new_llm_client', lambda: first)
    response = clients[0].post('/api/chat', json={'session_id': session['id'], 'message': '创建日程，去上海'})
    assert '尚未保存' in response.json()['messages'][-1]['content']
    second = FakeLLM([ToolCall('save', 'family_timed_memo_create', {'items': [
        {'title': '去上海', 'due_at': '2026-10-27T17:00:00+08:00'}]})])
    monkeypatch.setattr(web_app, '_new_llm_client', lambda: second)
    response = clients[0].post('/api/chat', json={'session_id': session['id'], 'message': '明天下午5点'})
    assert '已保存以下事项' in response.json()['messages'][-1]['content']
    assert len(service.store.snapshot()['tasks']) == 1
    assert not service.store.snapshot()['drafts']


@pytest.mark.parametrize('invalid_draft', ['expired', 'other-branch', 'deleted-source'])
def test_confirmation_never_reuses_an_unavailable_draft(api, monkeypatch, invalid_draft):
    clients, service, users, _ = api
    session = clients[0].post('/api/sessions').json()
    branch = 'different-branch' if invalid_draft == 'other-branch' else 'main'
    key = json.dumps([session['id'], branch, service.members.actor(users[0])])
    with service.store.transaction() as doc:
        doc['drafts'][key] = {'items': [{'title': '不得恢复的草稿', 'due_date': '2026-10-27'}],
            'user_id': users[0]['id'],
            'user_message_id': 'deleted-node' if invalid_draft == 'deleted-source' else session['active_node_id'],
            'expires_at': '2026-10-23T11:00:00+08:00' if invalid_draft == 'expired' else '2026-10-23T13:00:00+08:00'}
    model = ScriptedLLM([AgentModelResponse(content='请提供需要保存的内容。')])
    monkeypatch.setattr(web_app, '_new_llm_client', lambda: model)
    response = clients[0].post('/api/chat', json={'session_id': session['id'], 'message': '保存'})
    assert response.status_code == 200
    assert not model.requests[0][1].get('pending_draft')
    assert '不得恢复的草稿' not in json.dumps(model.requests, ensure_ascii=False)
    assert not service.store.snapshot()['tasks']


@pytest.mark.parametrize('household', [False, True])
def test_shared_chat_natural_creation_respects_scope(api, monkeypatch, household):
    clients, service, _, _ = api
    session = clients[0].post('/api/sessions').json()
    assert clients[0].patch(f"/api/sessions/{session['id']}/share", json={'scope': 'all'}).status_code == 200
    model = FakeLLM([ToolCall('new', 'family_undated_memo_create', {'items': [{'title': '买牛奶'}]})])
    monkeypatch.setattr(web_app, '_new_llm_client', lambda: model)
    message = '给全家记一条备忘，买牛奶' if household else '添加个人备忘，买牛奶'
    response = clients[0].post('/api/chat', json={'session_id': session['id'], 'message': message})
    assert response.status_code == 200
    assert len(service.store.snapshot()['tasks']) == (1 if household else 0)
    assert ('尚未保存' in response.json()['messages'][-1]['content']) != household


def test_old_session_uses_current_system_policy(api, monkeypatch):
    clients, _, _, _ = api
    session = clients[0].post('/api/sessions').json()
    messages = session['messages']
    root_id = messages[0]['node_id']
    messages[0]['content'] = '旧规则：必须输入斜杠标签，使用文本模拟执行命令。'
    web_app.store.save_messages(session['id'], messages)
    model = FakeLLM([ToolCall('new', 'family_undated_memo_create', {'items': [{'title': '买牛奶'}]})])
    original_method = model.achat_with_tools
    async def check(messages, schemas):
        assert '四种事项都支持自然语言创建' in messages[0]['content']
        assert messages[0]['node_id'] == root_id
        return await original_method(messages, schemas)
    model.achat_with_tools = check
    monkeypatch.setattr(web_app, '_new_llm_client', lambda: model)
    response = clients[0].post('/api/chat', json={'session_id': session['id'], 'message': '添加备忘，买牛奶'})
    assert response.status_code == 200
    assert '已保存以下事项' in response.json()['messages'][-1]['content']


def test_historical_success_and_other_branches_are_not_current_evidence():
    history = [{'role': 'tool', 'name': 'family_timed_memo_create', 'content': json.dumps({
        'status': 'success', 'output': {'tasks': [{'id': 'old'}]}})},
        {'role': 'user', 'content': '/ 日程'}]
    content, feedback = guard_task_answer('已成功创建日程', history,
        {'invocation': normalize_invocation('/ 日程'), 'raw_input': '/ 日程'})
    assert feedback and not content
    content, feedback = guard_task_answer('已创建的日程有一条', history,
        {'raw_input': '查询我的日程'})
    assert content == '已创建的日程有一条' and feedback is None
