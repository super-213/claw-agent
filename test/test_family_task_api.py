import asyncio
import json
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from agent_runtime import AgentModelResponse, ArtifactStore, MemoryStore, RunStore, ToolCall
from agent_runtime.builtin_tools import build_tool_registry
from agent_runtime.family_task_tools import register_family_task_tools
from agent_runtime.registry import ToolRegistry
from services.auth_service import AuthSessionStore
from services.conversation_store import ConversationStore
from services.executor import CommandExecutor
from services.task_store import TaskError
from family_task_helpers import invocation, create
import web_app


@pytest.fixture
def api(family, tmp_path, monkeypatch):
    service, users, clock = family
    from services.task_store import TaskStore
    monkeypatch.setattr(web_app, 'file_access_store', TaskStore(tmp_path / 'file-access.json'))
    monkeypatch.setattr(web_app, 'family_tasks', service)
    monkeypatch.setattr(web_app, 'family_members', service.members)
    monkeypatch.setattr(web_app, 'home_service', service.members.home)
    monkeypatch.setattr(web_app, 'user_store', service.members.users)
    monkeypatch.setattr(web_app, 'auth_sessions', AuthSessionStore())
    monkeypatch.setattr(web_app, 'store', ConversationStore(tmp_path / 'conversations'))
    monkeypatch.setattr(web_app, 'run_store', RunStore(tmp_path / 'runs'))
    monkeypatch.setattr(web_app, 'memory_store', MemoryStore(tmp_path / 'memory'))
    monkeypatch.setattr(web_app, 'artifact_store', ArtifactStore(tmp_path / 'artifacts'))
    monkeypatch.setitem(web_app.app.config, 'TESTING', False)
    monkeypatch.setitem(web_app.config.config, 'home_reminder_delivery_enabled', False)
    clients = []
    for user in users:
        client = TestClient(web_app.app)
        token = web_app.auth_sessions.create(user['id'])
        client.cookies.set(web_app.AUTH_COOKIE_NAME, token)
        clients.append(client)
    sender = Mock(side_effect=AssertionError('No delivery allowed'))
    monkeypatch.setattr(service.members.home, '_send_web_push_to_recipients', sender)
    return clients, service, users, clock


def payload(inv=None, title='买牛奶', rid='form-create', **fields):
    selected = inv or invocation()
    return {'request_id': rid, 'invocation': selected, 'items': [{'title': title, 'space_type': selected['space_type'],
            'temporal_type': selected['temporal_type'], **fields}]}


def test_two_account_end_to_end_assignment_complete_reopen(api):
    clients, service, users, _ = api
    alice, bob, carol = clients
    request = payload(invocation(temporal='timed', ids=['B']), title='交电费', due_date='2026-10-24')
    created = alice.post('/api/home/tasks', json=request)
    assert created.status_code == 201, created.text
    task = created.json()['tasks'][0]
    assert carol.get('/api/home/tasks/' + task['id']).status_code == 404
    assert carol.get('/api/home/tasks/summary?view=visible').json()['counts']['open'] == 0
    assert len(alice.get('/api/home/tasks?view=delegated').json()['items']) == 1
    row = bob.get('/api/home/tasks?due_from=2026-10-24&due_to=2026-10-24').json()['items'][0]
    occ = row['occurrence']
    url = f"/api/home/tasks/{task['id']}/occurrences/{occ['id']}"
    mutation = {'request_id': 'bob-complete', 'expected_version': occ['version']}
    assert alice.post(url + '/complete', json=mutation).status_code == 403
    done = bob.post(url + '/complete', json=mutation)
    assert done.status_code == 200 and done.json()['occurrence']['status'] == 'completed'
    assert bob.post(url + '/complete', json=mutation).json() == done.json()
    assert alice.get('/api/home/tasks?view=delegated&status=completed').json()['items'][0]['occurrence']['status'] == 'completed'
    reopened = bob.post(url + '/reopen', json={'request_id': 'reopen', 'expected_version': 2})
    assert reopened.status_code == 200 and reopened.json()['occurrence']['status'] == 'open'
    assert service.members.home._send_web_push_to_recipients.call_count == 0
    assert alice.post('/api/push/test', json={}).status_code == 409


def test_api_discriminators_summary_and_legacy_adapter(api):
    clients, service, _, _ = api
    alice, bob, _ = clients
    assert alice.post('/api/home/tasks', json=payload(due_date='2026-10-24')).status_code == 422
    assert alice.post('/api/home/tasks', json=payload(invocation(temporal='timed'))).json()['error'] == 'schedule_date_required'
    for index in range(3):
        assert alice.post('/api/home/tasks', json=payload(rid=str(index), title=f'条目{index}')).status_code == 201
    listing = alice.get('/api/home/tasks?limit=2').json()
    assert len(listing['items']) == 2 and listing['next_cursor'] == '2'
    assert alice.get('/api/home/tasks/summary').json()['counts']['undated'] == 3
    assert len(alice.get('/api/home/reminders').json()['reminders']) == 3
    assert not bob.get('/api/home/reminders').json()['reminders']
    assert alice.post('/api/home/reminders', json={'title': '旧接口'}).status_code == 409
    assert not service.members.home._notification_path().read_text()


class FakeLLM:
    model = 'fake-family-function-calling'
    context_window = 32768
    def __init__(self, calls):
        self.calls = calls
        self.turn = 0
    async def __aenter__(self):
        return self
    async def __aexit__(self, *_):
        return None
    async def achat_with_tools(self, messages, schemas):
        assert any(s['function']['name'] == 'family_timed_memo_create' for s in schemas)
        self.turn += 1
        return AgentModelResponse(tool_calls=self.calls) if self.turn == 1 else AgentModelResponse(content='处理结果以工具回执为准。')
    async def astream_with_tools(self, messages, schemas):
        yield {'type': 'done', 'response': await self.achat_with_tools(messages, schemas)}


@pytest.mark.parametrize('stream', [False, True])
def test_chat_native_function_call_identity_and_references(api, monkeypatch, stream):
    clients, service, _, _ = api
    alice, bob, _ = clients
    session = alice.post('/api/sessions').json()
    calls = [ToolCall('new-call-id', 'family_undated_memo_create', {'items': [{'title': '牛奶'}, {'title': '鸡蛋'}]})]
    monkeypatch.setattr(web_app, '_new_llm_client', lambda: FakeLLM(calls))
    body = {'session_id': session['id'], 'message': '/ 备忘 牛奶、鸡蛋', 'invocation': invocation(), 'request_id': 'chat-request'}
    response = alice.post('/api/chat/stream' if stream else '/api/chat', json=body)
    assert response.status_code == 200, response.text
    if stream:
        events = [json.loads(line) for line in response.text.splitlines()]
        assert any(event['type'] == 'task_changed' for event in events), events
        assert events[-1]['type'] == 'done'
    assert len(service.list(service.members.users.get_user(service.members.list()[0]['user_id']))['items']) == 2
    # A new tool_call_id on request retry still uses the request id operation ledger.
    calls[0] = ToolCall('regenerated-id', 'family_undated_memo_create', calls[0].arguments)
    retry = alice.post('/api/chat/stream' if stream else '/api/chat', json=body)
    assert retry.status_code == 200
    assert len(service.store.snapshot()['tasks']) == 2
    assert bob.get('/api/home/tasks?view=visible').json()['total'] == 0
    shared = alice.patch(f"/api/sessions/{session['id']}/share", json={'scope': 'all'})
    assert shared.status_code == 400 and shared.json()['error'] == 'private_task_history_cannot_be_shared'


def test_shared_session_does_not_persist_private_result(api, monkeypatch):
    clients, service, _, _ = api
    alice, _, _ = clients
    secret, _ = create((service, api[2], api[3]), items=[{'title': 'private-secret-title'}])
    session = alice.post('/api/sessions').json()
    assert alice.patch(f"/api/sessions/{session['id']}/share", json={'scope': 'all'}).status_code == 200
    monkeypatch.setattr(web_app, '_new_llm_client', lambda: FakeLLM([ToolCall('read', 'family_task_get', {'task_id': secret['id']})]))
    response = alice.post('/api/chat', json={'session_id': session['id'], 'message': '查询我的事项', 'request_id': 'shared'})
    assert response.status_code == 200
    history = web_app.store.load_session(session['id'])
    serialized = json.dumps(history, ensure_ascii=False)
    assert 'private-secret-title' not in serialized
    assert 'private_session_required' in serialized


def test_file_symlink_protection_and_no_shell(api, tmp_path):
    _, service, _, _ = api
    files = tmp_path / 'generated'
    files.mkdir()
    protected = service.store.path.parent
    protected_file = protected / 'secret.json'
    protected_file.write_text('private')
    (files / 'shortcut.json').symlink_to(protected_file)
    registry = build_tool_registry(project_root=tmp_path, generated_files_dir=files,
        executor=CommandExecutor(cwd=files), family_mode=True, protected_paths=(protected,))
    assert registry.get('shell_execute') is None and registry.get('shell.execute') is None
    for path in (protected_file, files / 'shortcut.json'):
        result = asyncio.run(registry.invoke(ToolCall('read', 'file_read', {'path': str(path)})))
        assert not result.success and 'protected_family_data' in result.error


def test_tool_conflict_draft_and_request_identity(api):
    _, service, users, _ = api
    registry = ToolRegistry()
    context = {'user_id': users[0]['id'], 'request_id': 'tool', 'session_id': 's', 'branch_id': 'main', 'invocation': None}
    register_family_task_tools(registry, service, lambda: users[0], lambda: context)
    result = asyncio.run(registry.invoke(ToolCall('draft', 'family_undated_memo_create', {'items': [{'title': '草稿'}]})))
    assert result.error == 'explicit_selection_required'
    assert result.output['draft'][0]['title'] == '草稿'
    assert not service.store.snapshot()['tasks'] and service.store.snapshot()['drafts']
    context['invocation'] = invocation()
    result = asyncio.run(registry.invoke(ToolCall('mismatch', 'family_timed_memo_create', {'items': [{'title': '时间', 'due_date': '2026-10-24'}]})))
    assert result.error == 'invocation_conflict'
    context['user_id'] = users[1]['id']
    result = asyncio.run(registry.invoke(ToolCall('identity', 'family_task_list', {})))
    assert result.error == 'run_identity_mismatch'


def test_generated_download_and_media_cannot_cross_accounts(api, tmp_path, monkeypatch):
    clients, _, users, _ = api
    root = tmp_path / 'files'
    own = root / users[0]['id']
    own.mkdir(parents=True)
    (own / 'private.txt').write_text('private export')
    monkeypatch.setattr(web_app, 'GENERATED_DIR', root)
    url = f"/generated/{users[0]['id']}/private.txt"
    assert clients[0].get(url).text == 'private export'
    assert clients[1].get(url).status_code == 404
    assert TestClient(web_app.app).get(url).status_code == 401
    session = clients[1].post('/api/sessions').json()
    response = clients[1].post('/api/chat', json={'session_id': session['id'], 'message': '读取附件',
        'attachments': [{'path': f"{users[0]['id']}/private.txt"}]})
    assert response.status_code == 404


def test_run_recovery_reauthenticates_original_actor(api, monkeypatch):
    clients, service, users, _ = api
    session = clients[0].post('/api/sessions').json()
    run = web_app.run_store.create(session_id=session['id'], goal='恢复', max_steps=5, max_runtime_seconds=30)
    web_app.run_store.update(run, actor_user_id=users[0]['id'], status='interrupted')
    # Admin/session authorization alone must not let a different actor use the run's task tools.
    orchestrator = web_app._build_orchestrator(users[1]['id'])
    async def resume():
        return [event async for event in orchestrator.resume_run_stream_async(run['id'])]
    with pytest.raises(PermissionError, match='run_identity_mismatch'):
        asyncio.run(resume())


def test_deleted_reference_and_branch_isolation(api):
    _, service, users, _ = api
    registry = ToolRegistry()
    context = {'user_id': users[0]['id'], 'request_id': 'reference', 'session_id': 's', 'branch_id': 'main',
               'invocation': invocation(), 'user_message_id': 'node-1', 'active_message_ids': ['node-1']}
    register_family_task_tools(registry, service, lambda: users[0], lambda: context)
    assert asyncio.run(registry.invoke(ToolCall('create', 'family_undated_memo_create', {'items': [{'title': '引用'}]}))).success
    assert asyncio.run(registry.invoke(ToolCall('get', 'family_task_get', {'task_id': 'recent'}))).success
    context['active_message_ids'] = []
    assert asyncio.run(registry.invoke(ToolCall('deleted', 'family_task_get', {'task_id': 'recent'}))).error == 'task_reference_expired'
    context['branch_id'] = 'other-branch'
    assert asyncio.run(registry.invoke(ToolCall('branch', 'family_task_get', {'task_id': 'recent'}))).error == 'task_reference_expired'


def test_forged_text_url_is_not_a_download_grant(api, tmp_path, monkeypatch):
    clients, _, users, _ = api
    root = tmp_path / 'files'
    own = root / users[0]['id']
    own.mkdir(parents=True)
    (own / 'private.txt').write_text('secret')
    monkeypatch.setattr(web_app, 'GENERATED_DIR', root)
    url = f"/generated/{users[0]['id']}/private.txt"
    session = clients[1].post('/api/sessions').json()
    web_app.store.save_messages(session['id'], [
        {'role': 'system', 'content': 'system'},
        {'role': 'user', 'content': url},
        {'role': 'assistant', 'content': url},
    ])
    assert clients[1].get(url).status_code == 404


def test_service_startup_never_sends_legacy_notifications(api, monkeypatch):
    _, service, _, _ = api
    spy = Mock(side_effect=AssertionError('scheduler must remain off'))
    monkeypatch.setattr(service.members.home, 'process_due_reminders', spy)
    with TestClient(web_app.app):
        assert spy.call_count == 0


def test_unresolved_member_draft_is_durable_and_not_a_task(api):
    clients, service, _, _ = api
    session = clients[0].post('/api/sessions').json()
    response = clients[0].post('/api/chat', json={'session_id': session['id'], 'message': '/ 备忘 @ 未选择 买牛奶'})
    assert response.status_code == 400 and response.json()['error'] == 'unresolved_mentions'
    doc = service.store.snapshot()
    assert not doc['tasks']
    assert next(iter(doc['drafts'].values()))['raw_input'] == '/ 备忘 @ 未选择 买牛奶'


def test_shared_recent_reference_cannot_bypass_private_boundary(api):
    _, service, users, clock = api
    task, _ = create((service, users, clock))
    registry = ToolRegistry()
    context = {'user_id': users[0]['id'], 'request_id': 'shared-ref', 'session_id': 's', 'branch_id': 'main',
               'session': {'owner_user_id': users[0]['id'], 'sharing': {'scope': 'all'}},
               'task_ref': {'task_id': task['id']}}
    register_family_task_tools(registry, service, lambda: users[0], lambda: context)
    result = asyncio.run(registry.invoke(ToolCall('recent', 'family_task_get', {'task_id': 'recent'})))
    assert result.error == 'private_session_required' and 'title' not in str(result.output)


def test_model_cannot_reassign_or_move_without_new_selection(api):
    _, service, users, clock = api
    task, _ = create((service, users, clock))
    registry = ToolRegistry()
    context = {'user_id': users[0]['id'], 'request_id': 'spoof', 'session_id': 's', 'branch_id': 'main', 'invocation': None}
    register_family_task_tools(registry, service, lambda: users[0], lambda: context)
    for patch in ({'assignee_ids': ['B']}, {'space_type': 'household', 'audience_confirmed': True}):
        result = asyncio.run(registry.invoke(ToolCall('change', 'family_task_update', {'task_id': task['id'],
              'expected_version': 1, 'patch': patch})))
        assert result.error == 'explicit_update_selection_required'
    assert service.get(users[0], task['id'])['task']['space_type'] == 'personal'


def test_copy_keeps_private_history_sharing_guard(api):
    clients, _, _, _ = api
    session = clients[0].post('/api/sessions').json()
    web_app.store.protect_private_task_history(session['id'])
    cloned = web_app.store.clone_session(session['id'])
    assert cloned['private_task_history']
    with pytest.raises(ValueError, match='private_task_history_cannot_be_shared'):
        web_app.store.update_sharing(cloned['id'], {'scope': 'all'})


def test_household_only_chat_can_still_be_shared(api, monkeypatch):
    clients, _, _, _ = api
    session = clients[0].post('/api/sessions').json()
    monkeypatch.setattr(web_app, '_new_llm_client', lambda: FakeLLM([
        ToolCall('public-create', 'family_undated_memo_create', {'items': [{'title': '洗衣液'}]})]))
    response = clients[0].post('/api/chat', json={'session_id': session['id'], 'message': '/ 家庭备忘 洗衣液',
        'invocation': invocation('household'), 'request_id': 'public-chat'})
    assert response.status_code == 200
    assert clients[0].patch(f"/api/sessions/{session['id']}/share", json={'scope': 'all'}).status_code == 200


def test_home_object_context_resolves_real_identity_and_preserves_permissions(api):
    clients, service, users, clock = api
    alice, bob, _ = clients
    task, _ = create((service, users, clock), items=[{'title': '真实私人标题'}])
    sid = alice.post('/api/sessions').json()['id']
    body = {'message': '处理这件事', 'object_context': {'type': 'family_task', 'id': task['id'], 'title': '伪造标题', 'source': '/home/tasks'}}
    context = web_app._task_chat_context(body, users[0], sid)
    assert context['task_ref']['task_id'] == task['id']
    assert context['object_context']['title'] == '真实私人标题'
    with pytest.raises(TaskError):
        web_app._task_chat_context(body, users[1], sid)
    # A selected private task must not be put into a shared conversation.
    assert alice.patch(f'/api/sessions/{sid}/share', json={'scope': 'all'}).status_code == 200
    with pytest.raises(TaskError, match='private_task_in_shared_session'):
        web_app._task_chat_context(body, users[0], sid)
    stock = service.members.home.add_inventory_item('medicine', {'name': '真实药品', 'quantity': 2}, users[0])['item']
    body = {'message': '处理物品', 'object_context': {'type': 'inventory_item', 'id': stock['id'], 'location': 'medicine', 'title': '错误物品'}}
    assert web_app._task_chat_context(body, users[0], sid)['object_context']['title'] == '真实药品'
    body['object_context']['location'] = 'fridge'
    with pytest.raises(TaskError, match='inventory_item_not_found'):
        web_app._task_chat_context(body, users[0], sid)


def test_inventory_clock_metadata_uses_household_timezone(api):
    clients, service, _, clock = api
    doc = clients[0].get('/api/home/inventory/medicine').json()
    assert doc['today'] == service.members.home._now().date().isoformat()
    assert doc['timezone'] == 'Asia/Shanghai'
    assert doc['as_of']
