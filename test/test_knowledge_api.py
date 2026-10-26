import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from agent_runtime import AgentModelResponse, ArtifactStore, MemoryStore, RunStore, ToolCall
from services.auth_service import AuthSessionStore
from services.conversation_store import ConversationStore
from services.knowledge_service import KnowledgeService
from services.task_store import TaskStore
import web_app


@pytest.fixture
def knowledge_api(family, tmp_path, monkeypatch):
    service, users, _ = family
    root = tmp_path / 'files'
    root.mkdir()
    knowledge = KnowledgeService(tmp_path / 'knowledge', service.members)
    for key, value in {'knowledge': knowledge, 'user_store': service.members.users, 'family_members': service.members,
        'family_tasks': service, 'auth_sessions': AuthSessionStore(), 'GENERATED_DIR': root, 'UPLOAD_DIR': root / 'uploads',
        'store': ConversationStore(tmp_path / 'sessions'), 'run_store': RunStore(tmp_path / 'runs'),
        'artifact_store': ArtifactStore(tmp_path / 'artifacts'), 'memory_store': MemoryStore(tmp_path / 'memory'),
        'file_access_store': TaskStore(tmp_path / 'file-access.json')}.items():
        monkeypatch.setattr(web_app, key, value)
    monkeypatch.setitem(web_app.app.config, 'TESTING', False)
    monkeypatch.setitem(web_app.config.config, 'home_reminder_delivery_enabled', False)
    clients = []
    for user in users:
        client = TestClient(web_app.app)
        client.cookies.set(web_app.AUTH_COOKIE_NAME, web_app.auth_sessions.create(user['id']))
        clients.append(client)
    return clients, users, knowledge


def upload(client, body='型号 AC-710。清洗滤网时先断电，再用清水冲洗。'):
    response = client.post('/api/chat/uploads', files=[('files', ('说明书.txt', body.encode(), 'text/plain'))])
    assert response.status_code == 200, response.text
    return response.json()['media'][0]


def mutate(row, patch=None, rid='edit'):
    return {'expected_version': row['version'], 'request_id': rid, 'patch': patch or {}}


def test_upload_save_search_share_revoke_delete_http(knowledge_api):
    (alice, bob, _), users, knowledge = knowledge_api
    media = upload(alice)
    payload = {'path': media['path'], 'title': '客厅空调', 'object_name': '空调', 'request_id': 'save'}
    saved = alice.post('/api/knowledge/documents', json=payload)
    assert saved.status_code == 201, saved.text
    row = saved.json()
    assert row['status'] == 'ready'
    assert alice.post('/api/knowledge/documents', json=payload).json()['id'] == row['id']
    assert bob.post('/api/knowledge/documents', json={**payload, 'request_id': 'steal'}).status_code == 404
    assert bob.get(row['file_url']).status_code == 404
    assert not bob.get('/api/knowledge/search?q=AC-710').json()['items']
    match = alice.get('/api/knowledge/search?q=AC-710').json()['items'][0]
    assert 'AC-710' in alice.get(match['source_url']).text
    assert 'no-store' in alice.get(match['source_url']).headers['cache-control']
    row = alice.patch('/api/knowledge/documents/' + row['id'], json=mutate(row, {'visibility': 'household'})).json()
    assert bob.get(row['file_url']).status_code == 200
    assert bob.get('/api/knowledge/search?q=AC-710').json()['items']
    row = alice.patch('/api/knowledge/documents/' + row['id'], json=mutate(row, {'visibility': 'personal'}, 'revoke')).json()
    assert not bob.get('/api/knowledge/search?q=AC-710').json()['items']
    assert bob.get(match['source_url']).status_code == 404
    url = '/api/knowledge/documents/' + row['id']
    removed = alice.request('DELETE', url, json=mutate(row, rid='delete'))
    assert removed.status_code == 200
    assert alice.request('DELETE', url, json=mutate(row, rid='delete')).json() == removed.json()
    assert not alice.get('/api/knowledge/search?q=AC-710').json()['items']
    assert alice.get('/generated/' + media['path']).status_code == 200


def test_record_source_escaping_conflicts_and_shared_edits(knowledge_api):
    (alice, bob, _), _, _ = knowledge_api
    row = alice.post('/api/knowledge/records', json={'title': '钥匙', 'content': '<script>alert(1)</script> 玄关',
        'request_id': 'remember'}).json()
    match = alice.get('/api/knowledge/search?q=钥匙').json()['items'][0]
    source = alice.get(match['source_url'])
    assert '<script>' not in source.text and '&lt;script&gt;' in source.text
    shared = alice.patch('/api/knowledge/records/' + row['id'], json=mutate(row, {'visibility': 'household'})).json()
    updated = bob.patch('/api/knowledge/records/' + row['id'], json=mutate(shared, {'content': '书房'}, 'bob-edit'))
    assert updated.status_code == 200
    assert alice.patch('/api/knowledge/records/' + row['id'], json=mutate(shared, {'content': '旧值'}, 'conflict')).status_code == 409
    assert alice.get(match['source_url']).status_code == 409
    assert bob.request('DELETE', '/api/knowledge/records/' + row['id'], json=mutate(updated.json(), rid='bob-delete')).status_code == 403


@pytest.mark.parametrize('streaming', [False, True])
def test_actual_runtime_tools_save_and_retrieve_in_new_session(knowledge_api, monkeypatch, streaming):
    (alice, bob, _), users, service = knowledge_api
    media = upload(alice)
    calls = []
    phase = ['save']

    class FakeLLM:
        model = 'knowledge-integration-stub'
        context_window = 32768
        def __init__(self): self.turn = 0
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        async def achat_with_tools(self, messages, tools):
            calls.append(messages)
            self.turn += 1
            if self.turn == 1:
                call = ToolCall('save', 'knowledge_document_save', {'path': media['path'], 'title': '空调说明书'}) if phase[0] == 'save' else ToolCall('find', 'knowledge_search', {'query': 'AC-710'})
                return AgentModelResponse(tool_calls=[call])
            result = json.loads(next(m['content'] for m in reversed(messages) if m.get('role') == 'tool'))
            assert result['status'] == 'success', result
            if phase[0] == 'save':
                return AgentModelResponse(content='已保存空调说明书，个人可见。')
            item = result['output']['items'][0]
            return AgentModelResponse(content=f"型号 AC-710。[来源]({item['source_url']})")
        async def astream_with_tools(self, messages, tools):
            yield {'type': 'done', 'response': await self.achat_with_tools(messages, tools)}

    monkeypatch.setattr(web_app, '_new_llm_client', FakeLLM)
    first = alice.post('/api/sessions').json()['id']
    url = '/api/chat/stream' if streaming else '/api/chat'
    saved = alice.post(url, json={'session_id': first, 'message': '帮我保存这份说明书', 'attachments': [media]})
    assert saved.status_code == 200, saved.text
    assert len(service.list(users[0], 'documents')) == 1
    # A private lookup must not be made shareable afterwards.
    assert alice.patch('/api/sessions/' + first + '/share', json={'scope': 'all', 'permission': 'read'}).status_code in {400, 409}
    phase[0] = 'search'
    second = alice.post('/api/sessions').json()['id']
    found = alice.post(url, json={'session_id': second, 'message': '之前的说明书，设备型号是什么'})
    assert found.status_code == 200
    persisted = alice.get('/api/sessions/' + second).json()['messages']
    assert any('/api/knowledge/documents/' in m.get('content', '') for m in persisted if m['role'] == 'assistant')
    assert web_app.memory_store.search('', scopes=[('session', second)]) == []


def test_tools_require_save_intent_and_private_session(knowledge_api):
    (alice, _, _), users, service = knowledge_api
    session = alice.post('/api/sessions').json()['id']
    ctx = web_app._task_chat_context({'message': '这张图片有什么'}, users[0], session)
    orchestrator = web_app._build_orchestrator(users[0]['id'], ctx)
    # Tools can be exercised without a model but still bind the live session identity.
    denied = asyncio.run(orchestrator.tool_registry.invoke(ToolCall('save', 'knowledge_record_save', {'title': '秘密', 'content': '不应自动保存'})))
    assert not denied.success and 'explicit_save_required' in str(denied.as_dict())
    assert not service.list(users[0], 'records')
    shared_session = alice.post('/api/sessions').json()['id']
    web_app.store.update_sharing(shared_session, {'scope': 'all', 'permission': 'write'})
    ctx = web_app._task_chat_context({'message': '之前的说明书'}, users[0], shared_session)
    orchestrator = web_app._build_orchestrator(users[0]['id'], ctx)
    denied = asyncio.run(orchestrator.tool_registry.invoke(ToolCall('search', 'knowledge_search', {'query': '秘密'})))
    assert not denied.success and 'private_session_required' in str(denied.as_dict())
