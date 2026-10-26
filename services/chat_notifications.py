"""Account-bound Web Push subscriptions and a durable completion outbox."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from threading import RLock
import time
from urllib.parse import urlsplit
import uuid

from .task_store import TaskError


def auth_fingerprint(token):
    return hashlib.sha256((token or '').encode()).hexdigest()


def validate_subscription(value):
    if not isinstance(value, dict):
        raise TaskError('invalid_subscription', '无效的推送订阅。')
    endpoint = str(value.get('endpoint') or '')
    try:
        url = urlsplit(endpoint)
        port = url.port
    except ValueError:
        raise TaskError('invalid_push_endpoint', '无效的推送地址。')
    host = url.hostname or ''
    allowed = host in {'web.push.apple.com', 'fcm.googleapis.com', 'updates.push.services.mozilla.com'} or host.endswith('.push.apple.com') or host.endswith('.notify.windows.com')
    if url.scheme != 'https' or not allowed or url.username or url.password or port not in (None, 443) or len(endpoint) > 4096 or url.fragment:
        raise TaskError('invalid_push_endpoint', '推送地址不是支持的浏览器推送服务。')
    keys = value.get('keys') or {}
    for name, size in [('p256dh', 65), ('auth', 16)]:
        encoded = keys.get(name, '')
        if not isinstance(encoded, str) or not re.fullmatch(r'[A-Za-z0-9_-]{10,150}={0,2}', encoded):
            raise TaskError('invalid_push_keys', '推送密钥格式错误。')
        try:
            decoded = base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4))
        except ValueError:
            raise TaskError('invalid_push_keys', '推送密钥格式错误。')
        if len(decoded) != size or (name == 'p256dh' and decoded[0] != 4):
            raise TaskError('invalid_push_keys', '推送密钥格式错误。')
    return {'endpoint': endpoint, 'keys': {key: keys[key] for key in ('p256dh', 'auth')}}


class ChatNotifications:
    def __init__(self, store, auth_valid, *, sender=None):
        self.store, self.auth_valid = store, auth_valid
        self.sender = sender or self._send
        self._keys_lock = RLock()

    def configuration(self):
        """Keep the private VAPID key on the server; provision once and back it up."""
        try:
            import pywebpush  # noqa: F401
        except ImportError:
            return {'configured': False, 'public_key': '', 'reason': '服务器缺少推送依赖，请安装 requirements.txt。'}
        subject = os.getenv('WEB_PUSH_SUBJECT', '')
        try:
            valid_subject = bool(re.fullmatch(r'mailto:[^\s@]+@[^\s@]+\.[^\s@]+', subject) or (subject.startswith('https://') and urlsplit(subject).hostname not in (None, 'localhost')))
        except ValueError:
            valid_subject = False
        public = os.getenv('WEB_PUSH_VAPID_PUBLIC_KEY', '')
        private = os.getenv('WEB_PUSH_VAPID_PRIVATE_KEY', '')
        if bool(public) != bool(private):
            return {'configured': False, 'public_key': '', 'reason': '服务器推送公私钥配置不完整。'}
        if not public:
            try:
                from cryptography.hazmat.primitives import serialization
                from cryptography.hazmat.primitives.asymmetric import ec
                with self._keys_lock:
                    key_path = self.store.path.parent / 'chat-vapid-private.pem'
                    if not key_path.exists():
                        key = ec.generate_private_key(ec.SECP256R1())
                        encoded = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
                        temporary = key_path.with_name('.chat-vapid-' + uuid.uuid4().hex + '.tmp')
                        try:
                            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                            with os.fdopen(fd, 'wb') as out:
                                out.write(encoded)
                                out.flush()
                                os.fsync(out.fileno())
                            os.replace(temporary, key_path)
                        finally:
                            temporary.unlink(missing_ok=True)
                    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
                    public = base64.urlsafe_b64encode(key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)).decode().rstrip('=')
                    private = str(key_path)
            except (ImportError, ValueError, OSError):
                return {'configured': False, 'public_key': '', 'reason': '推送密钥不可用，请检查依赖和服务器数据目录。'}
        return {'configured': valid_subject, 'public_key': public, 'reason': '' if valid_subject else '服务器需要配置 WEB_PUSH_SUBJECT 联系地址。', '_private': private, '_subject': subject}

    def config_public(self):
        return {key: value for key, value in self.configuration().items() if not key.startswith('_')}

    def subscribe(self, user_id, auth_hash, subscription):
        subscription = validate_subscription(subscription)
        if not self.configuration()['configured']:
            raise TaskError('push_not_configured', '服务器尚未完成推送配置。', status=503)
        endpoint_hash = hashlib.sha256(subscription['endpoint'].encode()).hexdigest()
        with self.store.db() as db:
            old = db.execute('SELECT id FROM chat_devices WHERE endpoint_hash=?', (endpoint_hash,)).fetchone()
            device_id = old['id'] if old else uuid.uuid4().hex
            db.execute('INSERT INTO chat_devices(id,endpoint_hash,user_id,auth_hash,subscription,enabled,updated_at) VALUES(?,?,?,?,?,1,?) ON CONFLICT(endpoint_hash) DO UPDATE SET user_id=excluded.user_id,auth_hash=excluded.auth_hash,subscription=excluded.subscription,enabled=1,updated_at=excluded.updated_at,last_error=NULL', (device_id, endpoint_hash, user_id, auth_hash, json.dumps(subscription), time.time()))
        return {'id': device_id, 'enabled': True}

    def disable(self, user_id, auth_hash, endpoint=None):
        with self.store.db() as db:
            sql, args = 'UPDATE chat_devices SET enabled=0 WHERE user_id=? AND auth_hash=?', [user_id, auth_hash]
            if endpoint:
                sql += ' AND endpoint_hash=?'
                args.append(hashlib.sha256(str(endpoint).encode()).hexdigest())
            db.execute(sql, args)
            db.execute("UPDATE chat_outbox SET status='cancelled' WHERE status='pending' AND device_id IN (SELECT id FROM chat_devices WHERE enabled=0)")

    def logout(self, auth_hash):
        with self.store.db() as db:
            db.execute('UPDATE chat_devices SET enabled=0 WHERE auth_hash=?', (auth_hash,))
            db.execute("UPDATE chat_outbox SET status='cancelled' WHERE status='pending' AND device_id IN (SELECT id FROM chat_devices WHERE enabled=0)")

    def current(self, user_id, auth_hash):
        with self.store.db() as db:
            devices = [dict(row) for row in db.execute('SELECT id,enabled,last_error FROM chat_devices WHERE user_id=? AND auth_hash=?', (user_id, auth_hash))]
            return {'devices': devices, **self.config_public()}

    def _send(self, subscription, payload):
        from pywebpush import webpush
        settings = self.configuration()
        if not settings['configured']:
            raise RuntimeError('push_not_configured')
        webpush(subscription_info=subscription, data=json.dumps(payload, ensure_ascii=False), vapid_private_key=settings['_private'], vapid_claims={'sub': settings['_subject']}, ttl=3600, timeout=10)

    def deliver_due(self):
        now = time.time()
        with self.store.db() as db:
            rows = [dict(row) for row in db.execute("SELECT o.*,j.user_id AS owner,j.session_id,j.status AS job_status,j.read_at,j.updated_at FROM chat_outbox o JOIN jobs j ON j.id=o.job_id WHERE o.status='pending' AND o.next_at<=? ORDER BY o.next_at LIMIT 10", (now,))]
        for notice in rows:
            with self.store.db() as db:
                device = db.execute('SELECT * FROM chat_devices WHERE id=?', (notice['device_id'],)).fetchone()
                job = db.execute('SELECT read_at,status FROM jobs WHERE id=?', (notice['job_id'],)).fetchone()
                invalid = not device or not device['enabled'] or device['user_id'] != notice['owner'] or not self.auth_valid(device['auth_hash'], notice['owner'])
                skip = 'read' if job and job['read_at'] else 'cancelled' if invalid else 'expired' if now - notice['updated_at'] > 3600 else None
                if skip:
                    db.execute('UPDATE chat_outbox SET status=? WHERE job_id=? AND device_id=?', (skip, notice['job_id'], notice['device_id']))
                    continue
                if db.execute("UPDATE chat_outbox SET status='sending',attempts=attempts+1 WHERE job_id=? AND device_id=? AND status='pending'", (notice['job_id'], notice['device_id'])).rowcount != 1:
                    continue
                subscription = json.loads(device['subscription'])
            state = notice['job_status']
            title = '回复已完成' if state == 'succeeded' else '有一项操作需要确认' if state in ('waiting_approval', 'waiting_user') else '任务未能完成'
            payload = {'kind': 'chat_result', 'title': title, 'body': '点击返回对话查看。', 'url': f"/sessions/{notice['session_id']}", 'tag': f"chat-{notice['job_id']}", 'job_id': notice['job_id']}
            try:
                # Recheck after claiming, so logout/read requests can revoke pending delivery.
                with self.store.db() as db:
                    current = db.execute('SELECT enabled,auth_hash,user_id FROM chat_devices WHERE id=?', (notice['device_id'],)).fetchone()
                    read = db.execute('SELECT read_at FROM jobs WHERE id=?', (notice['job_id'],)).fetchone()
                if not current or not current['enabled'] or current['user_id'] != notice['owner'] or not self.auth_valid(current['auth_hash'], notice['owner']) or read['read_at']:
                    status, error = 'cancelled', None
                else:
                    self.sender(subscription, payload)
                    status, error = 'sent', None
            except Exception as exc:
                response = getattr(exc, 'response', None)
                code = getattr(response, 'status_code', None)
                expired = code in (404, 410)
                status = 'expired' if expired else 'failed' if notice['attempts'] >= 4 else 'pending'
                error = 'subscription_expired' if expired else 'push_delivery_failed'
                if expired:
                    with self.store.db() as db:
                        db.execute('UPDATE chat_devices SET enabled=0,last_error=? WHERE id=?', (error, notice['device_id']))
            with self.store.db() as db:
                db.execute('UPDATE chat_outbox SET status=?,last_error=?,next_at=? WHERE job_id=? AND device_id=?', (status, error, now + min(300, 10 * 2 ** notice['attempts']), notice['job_id'], notice['device_id']))
                db.execute('UPDATE chat_devices SET last_error=? WHERE id=?', (error, notice['device_id']))
