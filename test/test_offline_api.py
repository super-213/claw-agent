from fastapi.testclient import TestClient
import pytest
from services.auth_service import AuthSessionStore
from services.knowledge_service import KnowledgeService
from services import ConversationStore, TokenUsageEstimator
from family_task_helpers import create
import web_app


@pytest.fixture
def offline(family, tmp_path, monkeypatch):
    service, people, _ = family
    monkeypatch.setattr(web_app, 'family_tasks', service)
    monkeypatch.setattr(web_app, 'family_members', service.members)
    monkeypatch.setattr(web_app, 'user_store', service.members.users)
    monkeypatch.setattr(web_app, 'auth_sessions', AuthSessionStore())
    monkeypatch.setattr(web_app, 'knowledge', KnowledgeService(tmp_path / 'knowledge', service.members))
    monkeypatch.setattr(web_app, 'store', ConversationStore(tmp_path / 'sessions', token_estimator=TokenUsageEstimator()))
    monkeypatch.setitem(web_app.app.config, 'TESTING', False)
    client = TestClient(web_app.app)
    client.post('/api/auth/login', json={'username': 'alice', 'password': 'secret123'})
    return client, service, people


def test_snapshot_whitelist_revalidation_and_permission_revocation(offline, family):
    client, service, people = offline
    task, _ = create(family, items=[{'title': 'safe title', 'description': 'sensitive secret body'}])
    private, _ = create(family, actor=1, rid='private', items=[{'title': 'bob private'}])
    result = client.post('/api/offline/snapshot', json={})
    assert result.status_code == 200 and result.headers['cache-control'] == 'no-store'
    snapshot = result.json()
    assert snapshot['scope']['user_id'] == people[0]['id']
    body = result.text
    assert 'sensitive secret body' not in body and 'bob private' not in body
    assert snapshot['data']['tasks'][0]['id'] == task['id']
    assert client.post('/api/offline/snapshot', json={'revision': snapshot['revision']}).json()['data'] is None
    service.members.update('A', {'status': 'disabled'}, people[0])
    assert client.post('/api/offline/snapshot', json={}).status_code == 403


def test_memo_idempotency_conflict_and_account_switch(offline):
    client, service, people = offline
    scope = client.post('/api/offline/snapshot', json={}).json()['scope']
    payload = {'title': 'offline memo', 'request_id': 'once', 'scope': scope}
    first = client.post('/api/offline/memos', json=payload)
    second = client.post('/api/offline/memos', json=payload)
    assert first.status_code == second.status_code == 200
    task = first.json()['tasks'][0]
    assert task['id'] == second.json()['tasks'][0]['id']
    assert len(service.store.snapshot()['tasks']) == 1
    change = {**payload, 'request_id': 'edit', 'task_id': task['id'], 'expected_version': task['version'], 'title': 'mine'}
    assert client.post('/api/offline/memos', json=change).status_code == 200
    assert client.post('/api/offline/memos', json={**change, 'request_id': 'stale', 'title': 'stale'}).status_code == 409
    client.post('/api/auth/logout')
    client.post('/api/auth/login', json={'username': 'bob', 'password': 'secret123'})
    assert client.post('/api/offline/memos', json=payload).status_code == 403
    assert task['id'] not in str(client.post('/api/offline/snapshot', json={}).json())


def test_cross_origin_write_rejected_before_side_effects(offline):
    client, service, _ = offline
    scope = client.post('/api/offline/snapshot', json={}).json()['scope']
    assert client.post('/api/offline/memos', headers={'Origin': 'https://evil.invalid'}, json={
        'title': 'bad', 'request_id': 'bad', 'scope': scope}).status_code == 403
    assert not service.store.snapshot()['tasks']


def test_revoked_shared_document_is_removed_by_incremental_validation(offline, tmp_path):
    client, _, people = offline
    document = tmp_path / 'manual.txt'
    document.write_text('Sensitive household document body')
    service = web_app.knowledge
    row = service.save_document(people[1], document, request_id='save', title='Appliance manual')
    row = service.change(people[1], 'documents', row['id'], {'visibility': 'household'},
                         expected_version=row['version'], request_id='share')
    snapshot = client.post('/api/offline/snapshot', json={}).json()
    assert snapshot['data']['documents'][0]['title'] == 'Appliance manual'
    assert 'Sensitive household document body' not in str(snapshot)
    service.change(people[1], 'documents', row['id'], {'visibility': 'personal'},
                   expected_version=row['version'], request_id='revoke')
    refreshed = client.post('/api/offline/snapshot', json={'revision': snapshot['revision']}).json()
    assert refreshed['revision'] != snapshot['revision']
    assert refreshed['data']['documents'] == []


def test_revoked_member_cannot_read_or_mutate_shared_inventory(offline):
    client, service, people = offline
    service.members.update('A', {'status': 'disabled'}, people[0])
    assert client.get('/api/home/inventory').status_code == 403
    assert client.get('/api/home/inventory/fridge').status_code == 403
    assert client.get('/api/home/inventory/expiring').status_code == 403
    assert client.post('/api/home/inventory/fridge/items', json={'name': 'forbidden'}).status_code == 403
