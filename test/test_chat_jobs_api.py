import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient
from fastapi.responses import StreamingResponse

import web_app as w
from agent_runtime import RunStore
from services import ConversationStore, UserStore
from services.auth_service import AuthSessionStore
from services.chat_jobs import BackgroundChat, ChatJobStore
from services.chat_notifications import ChatNotifications, auth_fingerprint


@pytest.fixture
def jobs_api(tmp_path, monkeypatch):
    users = UserStore(tmp_path / 'users.json')
    auth = AuthSessionStore()
    conversations = ConversationStore(tmp_path / 'conversations')
    jobs = ChatJobStore(tmp_path / 'jobs.sqlite3')
    sent = []
    notifications = ChatNotifications(jobs, auth.is_active_hash, sender=lambda *args: sent.append(args))
    engine = BackgroundChat(jobs, notifications)
    monkeypatch.setattr(w, 'user_store', users)
    monkeypatch.setattr(w, 'auth_sessions', auth)
    monkeypatch.setattr(w, 'store', conversations)
    monkeypatch.setattr(w, 'run_store', RunStore(tmp_path / 'runs'))
    monkeypatch.setattr(w, 'chat_background', engine)
    monkeypatch.setitem(w.app.config, 'TESTING', False)
    monkeypatch.setitem(w.config.config, 'home_reminder_delivery_enabled', False)
    calls = []
    async def stream(payload, user):
        async def source():
            calls.append(payload.message)
            yield json.dumps({'type': 'model_start'}) + '\n'
            await asyncio.sleep(.2)
            session = conversations.load_session(payload.session_id)
            messages = [{'role': 'user', 'content': payload.message}, {'role': 'assistant', 'content': 'saved answer'}]
            conversations.save_messages(payload.session_id, session['messages'] + messages)
            yield json.dumps({'type': 'done', 'run_status': 'completed', 'messages': messages}) + '\n'
        return StreamingResponse(source())
    monkeypatch.setattr(w, 'chat_stream', stream)
    with TestClient(w.app) as client:
        client.post('/api/auth/bootstrap-admin', json={'username': 'alice', 'password': 'test-password'})
        session = client.post('/api/sessions').json()['id']
        yield client, session, jobs, calls, notifications


def wait_finished(client, job_id):
    for _ in range(100):
        job = client.get('/api/chat/jobs/' + job_id).json()['job']
        if job['status'] not in ('queued', 'running'):
            return job
        time.sleep(.02)
    pytest.fail('Background job did not finish')


def test_background_job_api_dedup_saved_result_and_read_ack(jobs_api):
    client, session, store, calls, notices = jobs_api
    payload = {'session_id': session, 'message': 'private question', 'request_id': 'request-0001'}
    response = client.post('/api/chat/jobs', json=payload)
    assert response.status_code == 202, response.text
    job = response.json()['job']
    assert client.post('/api/chat/jobs', json=payload).json()['job']['id'] == job['id']
    assert client.post('/api/chat/jobs', json={**payload, 'message': 'changed'}).status_code == 409
    assert client.delete('/api/sessions/' + session).status_code == 409
    done = wait_finished(client, job['id'])
    assert done['status'] == 'succeeded'
    assert calls == ['private question']
    assert client.get('/api/sessions/' + session).json()['messages'][-1]['content'] == 'saved answer'
    assert client.get('/api/sessions/' + session + '/chat-job').json()['job']['id'] == job['id']
    assert client.post('/api/chat/jobs/' + job['id'] + '/read').status_code == 200
    assert store.get(job['id'], client.get('/api/auth/me').json()['user']['id'])['read_at']
    assert 'payload' not in client.get('/api/chat/jobs/' + job['id']).json()['job']


def test_job_status_and_events_are_private_even_from_other_admins(jobs_api):
    client, session, store, calls, notices = jobs_api
    job = client.post('/api/chat/jobs', json={'session_id': session, 'message': 'secret', 'request_id': 'request-0001'}).json()['job']
    wait_finished(client, job['id'])
    client.post('/api/admin/users', json={'username': 'bob', 'password': 'test-password', 'role': 'admin'})
    client.post('/api/auth/logout')
    client.post('/api/auth/login', json={'username': 'bob', 'password': 'test-password'})
    for suffix in ['', '/events']:
        assert client.get('/api/chat/jobs/' + job['id'] + suffix).status_code == 404
    assert client.post('/api/chat/jobs/' + job['id'] + '/cancel').status_code == 404
    assert client.get('/api/sessions/' + session + '/chat-job').json()['job'] is None
    assert client.post('/api/runs/missing/background-resume', json={'request_id': 'resume-00001'}).status_code == 404


def test_logout_revokes_device_and_push_configuration_has_no_private_key(jobs_api, monkeypatch):
    client, session, store, calls, notices = jobs_api
    monkeypatch.setenv('WEB_PUSH_SUBJECT', 'mailto:test@example.com')
    monkeypatch.delenv('WEB_PUSH_VAPID_PUBLIC_KEY', raising=False)
    monkeypatch.delenv('WEB_PUSH_VAPID_PRIVATE_KEY', raising=False)
    config = client.get('/api/chat-notifications').json()
    assert config['configured'] and config['public_key']
    assert '_private' not in config and '_subject' not in config
    import base64
    encode = lambda value: base64.urlsafe_b64encode(value).decode().rstrip('=')
    sub = {'endpoint': 'https://web.push.apple.com/api-test', 'keys': {'p256dh': encode(b'\x04' + bytes(64)), 'auth': encode(bytes(16))}}
    assert client.post('/api/chat-notifications/subscribe', json={'subscription': sub}).status_code == 200
    assert client.get('/api/chat-notifications').json()['devices'][0]['enabled']
    token = client.cookies.get(w.AUTH_COOKIE_NAME)
    client.post('/api/auth/logout')
    with store.db() as db:
        assert db.execute('SELECT enabled FROM chat_devices WHERE auth_hash=?', (auth_fingerprint(token),)).fetchone()[0] == 0


def test_background_cancel_stops_server_work(jobs_api):
    client, session, store, calls, notices = jobs_api
    job = client.post('/api/chat/jobs', json={'session_id': session, 'message': 'stop me', 'request_id': 'request-0001'}).json()['job']
    assert client.post('/api/chat/jobs/' + job['id'] + '/cancel').status_code == 200
    assert wait_finished(client, job['id'])['status'] == 'cancelled'
