import base64
import json
from types import SimpleNamespace
import time

import pytest

from services.chat_jobs import ChatJobStore
from services.chat_notifications import ChatNotifications, auth_fingerprint, validate_subscription
from services.auth_service import AuthSessionStore
from services.task_store import TaskError


def subscription(endpoint='https://web.push.apple.com/example'):
    encode = lambda value: base64.urlsafe_b64encode(value).decode().rstrip('=')
    return {'endpoint': endpoint, 'keys': {'p256dh': encode(b'\x04' + bytes(64)), 'auth': encode(bytes(16))}}


def setup_notifications(tmp_path):
    store = ChatJobStore(tmp_path / 'jobs.sqlite3')
    sent = []
    notices = ChatNotifications(store, lambda auth, user: auth == 'valid' and user == 'alice', sender=lambda sub, payload: sent.append((sub, payload)))
    notices.configuration = lambda: {'configured': True, 'public_key': 'key'}
    return store, notices, sent


def complete(store, request='request-0001'):
    job, _ = store.create('alice', 'private-session', request, {'message': 'PRIVATE QUESTION'})
    store.append(job['id'], {'type': 'done', 'run_status': 'completed', 'messages': [{'content': 'PRIVATE ANSWER'}]})
    with store.db() as db:
        db.execute('UPDATE chat_outbox SET next_at=0')
    return job


def test_completion_push_is_private_deduplicated_and_read_result_is_suppressed(tmp_path):
    store, notices, sent = setup_notifications(tmp_path)
    notices.subscribe('alice', 'valid', subscription())
    job = complete(store)
    notices.deliver_due()
    notices.deliver_due()
    assert len(sent) == 1
    assert sent[0][1]['url'] == '/sessions/private-session'
    assert sent[0][1]['tag'] == 'chat-' + job['id']
    assert 'PRIVATE' not in json.dumps(sent)
    second = complete(store, 'request-0002')
    store.read(second['id'], 'alice')
    notices.deliver_due()
    assert len(sent) == 1


def test_logout_and_account_switch_revoke_delivery(tmp_path):
    store, notices, sent = setup_notifications(tmp_path)
    notices.subscribe('alice', 'valid', subscription())
    complete(store)
    notices.logout('valid')
    notices.deliver_due()
    assert not sent
    notices.subscribe('alice', 'valid', subscription())
    complete(store, 'request-0002')
    notices.subscribe('bob', 'other-login', subscription())
    notices.deliver_due()
    assert not sent


def test_retry_then_expired_subscription_and_failure_do_not_change_chat_result(tmp_path):
    store, notices, sent = setup_notifications(tmp_path)
    device = notices.subscribe('alice', 'valid', subscription())
    job = complete(store)
    class PushFailure(Exception):
        response = SimpleNamespace(status_code=503)
    def fail(*args):
        raise PushFailure()
    notices.sender = fail
    notices.deliver_due()
    with store.db() as db:
        record = db.execute('SELECT * FROM chat_outbox').fetchone()
        assert record['status'] == 'pending' and record['attempts'] == 1
        db.execute('UPDATE chat_outbox SET next_at=0')
    PushFailure.response = SimpleNamespace(status_code=410)
    notices.deliver_due()
    with store.db() as db:
        assert db.execute('SELECT enabled FROM chat_devices WHERE id=?', (device['id'],)).fetchone()[0] == 0
        assert db.execute('SELECT status FROM chat_outbox').fetchone()[0] == 'expired'
    assert store.get(job['id'], 'alice')['status'] == 'succeeded'


@pytest.mark.parametrize('endpoint', ['http://127.0.0.1/x', 'https://localhost/x', 'https://web.push.apple.com.evil.example/x', 'https://web.push.apple.com:bad/x', 'https://user@web.push.apple.com/x'])
def test_untrusted_push_endpoints_are_rejected(endpoint):
    with pytest.raises(TaskError):
        validate_subscription(subscription(endpoint))


def test_login_check_does_not_extend_expiration_and_vapid_key_is_stable(tmp_path, monkeypatch):
    auth = AuthSessionStore()
    token = auth.create('alice')
    fingerprint = auth_fingerprint(token)
    before = auth._sessions[fingerprint]['expires_at']
    assert auth.is_active_hash(fingerprint, 'alice')
    assert auth._sessions[fingerprint]['expires_at'] == before
    auth.delete(token)
    assert not auth.is_active_hash(fingerprint, 'alice')
    monkeypatch.delenv('WEB_PUSH_VAPID_PUBLIC_KEY', raising=False)
    monkeypatch.delenv('WEB_PUSH_VAPID_PRIVATE_KEY', raising=False)
    monkeypatch.setenv('WEB_PUSH_SUBJECT', 'mailto:test@example.com')
    store = ChatJobStore(tmp_path / 'jobs.sqlite3')
    first = ChatNotifications(store, lambda *_: True).config_public()
    second = ChatNotifications(store, lambda *_: True).config_public()
    assert first['configured'] and first['public_key'] == second['public_key']
    assert not any(key.startswith('_') for key in first)
