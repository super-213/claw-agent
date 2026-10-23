"""Explicit account bindings and speaker-relative family names."""
from __future__ import annotations

import fcntl
import json
from threading import RLock
from services.task_store import TaskError, TaskStore


class FamilyMemberService:
    def __init__(self, home_service, user_store):
        self.home = home_service
        self.users = user_store
        self.lock = RLock()

    def list(self):
        path = self.home.root_dir / 'household.json'
        try:
            doc = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'members': []}
            rows = doc.get('members') or []
            if not isinstance(rows, list):
                raise ValueError()
        except (OSError, ValueError, AttributeError) as exc:
            raise TaskError('household_corrupt', '家庭成员配置损坏；原文件未改动。', status=503) from exc
        result = []
        for row in rows:
            if not isinstance(row, dict) or not row.get('member_id'):
                continue
            user = self.users.get_user(row.get('user_id'))
            result.append({**row, 'status': 'active' if user and user.get('status') == 'active'
                           and row.get('status', 'active') == 'active' else 'disabled'})
        return result

    def actor(self, user):
        if not user or user.get('status') != 'active':
            raise TaskError('unauthorized', status=401)
        member = next((m for m in self.list() if m['user_id'] == user['id'] and m['status'] == 'active'), None)
        if not member:
            raise TaskError('member_not_bound', '请管理员先将当前账号绑定为家庭成员。', status=403)
        return member['member_id']

    def validate(self, ids):
        if not isinstance(ids, list) or not all(isinstance(mid, str) for mid in ids) or len(ids) != len(set(ids)):
            raise TaskError('invalid_members')
        active = {m['member_id'] for m in self.list() if m['status'] == 'active'}
        if any(mid not in active for mid in ids):
            raise TaskError('member_unavailable', '成员不存在或已停用，请重新选择。')
        return list(ids)

    def update(self, member_id, patch, admin):
        if admin.get('role') != 'admin' or admin.get('status') != 'active':
            raise TaskError('forbidden', status=403)
        if set(patch) - {'user_id', 'display_name', 'aliases', 'status', 'speaker_aliases'}:
            raise TaskError('invalid_member_fields')
        path = self.home.root_dir / 'household.json'
        with self.lock, self.home._lock, path.with_suffix('.lock').open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                doc = json.loads(path.read_text(encoding='utf-8'))
                rows = doc.setdefault('members', [])
                row = next((m for m in rows if m.get('member_id') == member_id), None)
                value = {**(row or {}), **patch, 'member_id': member_id}
                account = self.users.get_user(value.get('user_id'))
                if not account or account.get('status') != 'active':
                    raise TaskError('invalid_account_binding')
                if any(m.get('user_id') == value['user_id'] and m.get('member_id') != member_id for m in rows):
                    raise TaskError('account_already_bound')
                if not value.get('display_name') or value.get('status', 'active') not in {'active', 'disabled'}:
                    raise TaskError('invalid_member')
                if not isinstance(value.get('aliases', []), list) or not all(isinstance(a, str) for a in value.get('aliases', [])):
                    raise TaskError('invalid_aliases')
                if (not isinstance(value.get('speaker_aliases', {}), dict) or
                    any(not isinstance(alias, str) or not isinstance(target, str) or target not in {member_id, *(m.get('member_id') for m in rows)}
                        for alias, target in value.get('speaker_aliases', {}).items())):
                    raise TaskError('invalid_aliases')
                value.setdefault('status', 'active')
                value.setdefault('aliases', [])
                if row is None:
                    rows.append(value)
                else:
                    row.update(value)
                TaskStore.write_atomic(path, doc)
                return value
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def resolve(self, text, user):
        actor = self.actor(user)
        rows = [m for m in self.list() if m['status'] == 'active']
        if text in {'我', '我的'}:
            return [m for m in rows if m['member_id'] == actor]
        exact = [m for m in rows if text == m['member_id'] or text == m['display_name']]
        if exact:
            return exact
        speaker = next(m for m in rows if m['member_id'] == actor)
        target = speaker.get('speaker_aliases', {}).get(text)
        if target:
            return [m for m in rows if m['member_id'] == target]
        return [m for m in rows if text in m.get('aliases', [])]
