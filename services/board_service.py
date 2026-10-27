"""Shared paper notes: all entry points use the same permissions and transactions."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from io import BytesIO
import hashlib
import json
import re
import uuid
from zoneinfo import ZoneInfo

from PIL import Image, ImageOps, UnidentifiedImageError
from services.task_access import check_version
from services.task_store import TaskError
from services.board_store import purge_expired

MAX_IMAGE_BYTES = 10 * 1024 * 1024
FIELDS = {'title', 'content_blocks', 'audience_mode', 'recipient_ids', 'retention_mode', 'expires_at', 'duration_hours'}


class BoardPostService:
    def __init__(self, store, members, *, timezone_name='Asia/Shanghai', clock=None):
        self.store, self.members = store, members
        self.timezone_name, self.clock = timezone_name, clock
        self.store.clock = self.now
        self.asset_root = store.path.parent / 'board-assets'
        self.asset_root.mkdir(parents=True, exist_ok=True)

    def now(self):
        value = self.clock() if self.clock else datetime.now(timezone.utc)
        return value.astimezone(timezone.utc)

    def cleanup_expired(self):
        """Remove expired payloads without requiring an open page or active user."""
        with self.store.transaction() as doc:
            now = self.now()
            removed = purge_expired(doc, now)
            # Existing daily backups follow the same retention as the live note.
            # The backup hook also strips expired data from the snapshot produced
            # when this transaction commits.
            backup_assets = set()
            for path in (self.store.path.parent / 'backups').glob(self.store.path.stem + '-*.json'):
                try:
                    snapshot = json.loads(path.read_text(encoding='utf-8'))
                except (ValueError, OSError):
                    raise TaskError('board_backup_corrupt', '便笺备份损坏，无法完成到期清理。', status=503)
                before = deepcopy(snapshot)
                purged = purge_expired(snapshot, now, post_ids=removed['post_ids'], draft_ids=removed['draft_ids'])
                backup_assets.update(purged['asset_ids'])
                if snapshot != before:
                    self.store.write_atomic(path, snapshot)
            # Retain images still used by a different live note or draft.
            referenced = {asset for collection in ('posts', 'drafts') for record in doc[collection].values() for asset in self._assets(record)}
            for asset_id in (removed['asset_ids'] | backup_assets) - referenced:
                doc['assets'].pop(asset_id, None)
                if re.fullmatch(r'asset_[a-f0-9]{32}', asset_id):
                    (self.asset_root / (asset_id + '.png')).unlink(missing_ok=True)
            return {'destroyed_count': len(removed['post_ids']), 'destroyed_ids': sorted(removed['post_ids'])}

    @staticmethod
    def _date(value):
        try:
            result = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if result.tzinfo is None:
                raise ValueError()
            return result.astimezone(timezone.utc)
        except (ValueError, TypeError, AttributeError):
            raise TaskError('invalid_expiration', '请选择带时区的截止时间。')

    @staticmethod
    def _assets(value):
        return {b['asset_id'] for b in value.get('content_blocks', []) if b['type'] == 'image'}

    def _can_read(self, post, actor):
        return actor == post['created_by'] or (post['publication_state'] != 'withdrawn' and
            (post['audience_mode'] == 'household' or actor in post['recipient_ids']))

    def _post(self, doc, post_id, actor):
        post = doc['posts'].get(post_id)
        if not post or self._state(post, self.now()) == 'expired' or not self._can_read(post, actor):
            raise TaskError('board_post_not_found', '该便笺已不可访问。', status=404)
        return post

    def _state(self, post, now):
        if post['expires_at'] and now >= self._date(post['expires_at']):
            return 'expired'
        return 'withdrawn' if post['publication_state'] == 'withdrawn' else 'active'

    def _context(self, value, context, *, draft=False, write=False):
        if not context:
            if draft and value.get('session_id'):
                raise TaskError('draft_session_required', '请在原会话中读取草稿。', status=403)
            return
        if write and context.get('read_only_session'):
            raise TaskError('read_only_session', '该会话只可查看。', status=403)
        if draft and value.get('session_id'):
            if (context.get('session_id') != value['session_id'] or context.get('branch_id', 'main') != value['branch_id']
                    or value.get('user_message_id') and value['user_message_id'] not in context.get('active_message_ids', [])):
                raise TaskError('board_draft_not_found', status=404)
        # Keep board payloads out of shareable chat history, even if the post is
        # currently household-visible: its audience can subsequently shrink.
        if context.get('session_id'):
            if context.get('shared'):
                raise TaskError('private_session_required', '请在个人对话中配置或查看便笺。', status=403)
            if context.get('protect_private_session'):
                context['protect_private_session']()

    def _view(self, doc, value, actor, now, *, draft=False, context=None):
        self._context(value, context, draft=draft)
        state = 'draft' if draft else self._state(value, now)
        deadline = value['draft_expires_at'] if draft else value['expires_at']
        editable = (draft or state == 'active') and value['created_by'] == actor and not (context or {}).get('read_only_session')
        actions = (['save_draft', 'publish'] if draft else ['save', 'withdraw']) if editable else []
        public = {k: deepcopy(v) for k, v in value.items() if k not in {'source', 'session_id', 'branch_id', 'user_message_id', 'committed_post_id'}}
        public['state'] = state
        return {'resource': {'type': 'board_post_draft' if draft else 'board_post', 'id': value['id']},
                'mode': 'draft' if draft else 'saved', 'post': public, 'server_now': now.isoformat(),
                'timezone': self.timezone_name, 'valid_until': deadline, 'next_transition_at': deadline,
                'current_member_id': actor, 'revision': doc['revision'],
                'members': [{k: m.get(k) for k in ('member_id', 'display_name', 'status', 'aliases')} for m in self.members.list()],
                'read_only': not editable, 'read_only_reason': None if editable else state if state != 'active' else 'not_permitted',
                'capabilities': {'editable_fields': sorted(FIELDS) if editable else [], 'actions': actions}}

    def _normalize(self, doc, actor, data, now, *, draft=False, publishing=False):
        if not isinstance(data, dict) or set(data) - FIELDS:
            raise TaskError('invalid_board_fields', '便笺包含不支持的字段。')
        title = data.get('title', '')
        blocks = data.get('content_blocks', [])
        if not isinstance(title, str) or len(title) > 120 or not isinstance(blocks, list) or len(blocks) > 100:
            raise TaskError('invalid_board_content', '请检查标题及正文。')
        clean, text_length, image_count = [], 0, 0
        for block in blocks:
            if not isinstance(block, dict):
                raise TaskError('invalid_board_content')
            if block.get('type') == 'text' and set(block) <= {'type', 'text'} and isinstance(block.get('text'), str):
                text_length += len(block['text'])
                if block['text'].strip():
                    clean.append({'type': 'text', 'text': block['text']})
            elif block.get('type') == 'image' and set(block) <= {'type', 'asset_id', 'alt'} and isinstance(block.get('asset_id'), str):
                asset = doc['assets'].get(block['asset_id'])
                if not asset or asset['created_by'] != actor:
                    raise TaskError('board_asset_not_found', '图片不可用，请重新选择。', status=404)
                alt = block.get('alt', '')
                if not isinstance(alt, str) or len(alt) > 500:
                    raise TaskError('invalid_board_content')
                clean.append({'type': 'image', 'asset_id': asset['id'], 'alt': alt})
                image_count += 1
            else:
                raise TaskError('invalid_board_content')
        if text_length > 10000 or image_count > 9:
            raise TaskError('board_content_too_large', '便笺最多 10,000 字和 9 张图片。')
        audience = data.get('audience_mode', 'selected')
        ids = data.get('recipient_ids', [])
        if audience not in {'selected', 'household'} or not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            raise TaskError('invalid_audience')
        ids = list(dict.fromkeys(ids))
        if audience == 'household' and ids:
            raise TaskError('audience_conflict', '所有人与指定成员不能同时选择。')
        self.members.validate(ids)
        retention = data.get('retention_mode', 'permanent')
        expires = data.get('expires_at')
        duration = data.get('duration_hours')
        if retention not in {'permanent', 'until'}:
            raise TaskError('invalid_retention')
        if retention == 'permanent':
            if expires is not None or duration is not None:
                raise TaskError('retention_conflict', '长期便笺不设置截止时间。')
        else:
            if duration is not None:
                if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not 0 < duration <= 87600 or expires:
                    raise TaskError('invalid_expiration')
                if publishing:
                    expires, duration = (now + timedelta(hours=duration)).isoformat(), None
            if expires:
                expires = self._date(expires).isoformat()
                if self._date(expires) <= now:
                    raise TaskError('board_expired', '截止时间已过，请选择未来时间；如需结束展示请撤下。', status=409)
        missing = []
        if not clean:
            missing.append('文字或图片')
        if audience == 'selected' and not ids:
            missing.append('接收人')
        if retention == 'until' and not expires and duration is None:
            missing.append('截止时间')
        if not draft and missing:
            raise TaskError('board_fields_required', '请补充：' + '、'.join(missing), missing_fields=missing)
        return {'title': title.strip(), 'content_blocks': clean, 'audience_mode': audience, 'recipient_ids': ids,
                'retention_mode': retention, 'expires_at': expires, 'duration_hours': duration, 'missing_fields': missing}

    def _operation(self, user, request_id, signature, apply, *, context=None):
        actor = self.members.actor(user)
        self.cleanup_expired()
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 200:
            raise TaskError('request_id_required')
        fingerprint = hashlib.sha256(json.dumps(signature, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        key = actor + ':' + request_id
        with self.store.transaction() as doc:
            now = self.now()
            previous = doc['operations'].get(key)
            if previous:
                if previous['fingerprint'] != fingerprint:
                    raise TaskError('request_id_conflict', '该请求编号已用于其他修改。', status=409)
                return self._get(doc, previous['resource_id'], actor, now, draft=previous['draft'], context=context)
            value, draft = apply(doc, actor, now)
            doc['operations'][key] = {'fingerprint': fingerprint, 'resource_id': value['id'], 'draft': draft}
            doc['events'].append({'action': signature['action'], 'resource_id': value['id'], 'actor': actor, 'at': now.isoformat()})
            result = self._view(doc, value, actor, now, draft=draft, context=context)
            result['resource_changed'] = {'type': 'resource_changed', 'resource_type': result['resource']['type'],
                                          'resource_id': value['id'], 'revision': doc['revision'] + 1}
            return result

    def create(self, user, data, *, request_id, draft=False, context=None):
        def apply(doc, actor, now):
            value = self._normalize(doc, actor, data, now, draft=draft, publishing=not draft)
            value.update(id=('board_draft_' if draft else 'post_') + uuid.uuid4().hex, created_by=actor,
                         household_id='household', version=1, timezone=self.timezone_name,
                         created_at=now.isoformat(), updated_at=now.isoformat(), resource_refs=[])
            if draft:
                value.update(draft_expires_at=(now + timedelta(minutes=30)).isoformat(),
                             session_id=(context or {}).get('session_id'), branch_id=(context or {}).get('branch_id', 'main'),
                             user_message_id=(context or {}).get('user_message_id'))
            else:
                value.update(publication_state='published', published_at=now.isoformat(), withdrawn_at=None)
            self._context(value, context, draft=draft, write=True)
            doc['drafts' if draft else 'posts'][value['id']] = value
            return value, draft
        return self._operation(user, request_id, {'action': 'draft' if draft else 'publish', 'data': data}, apply, context=context)

    def _draft(self, doc, draft_id, actor, now, context):
        value = doc['drafts'].get(draft_id)
        if not value or value['created_by'] != actor:
            raise TaskError('board_draft_not_found', status=404)
        self._context(value, context, draft=True)
        if not value.get('committed_post_id') and now >= self._date(value['draft_expires_at']):
            raise TaskError('board_draft_expired', '草稿已过期，请重新创建。', status=410)
        return value

    def _get(self, doc, resource_id, actor, now, *, draft=False, context=None):
        if draft:
            value = self._draft(doc, resource_id, actor, now, context)
            if value.get('committed_post_id'):
                return self._get(doc, value['committed_post_id'], actor, now, context=context)
        else:
            value = self._post(doc, resource_id, actor)
        return self._view(doc, value, actor, now, draft=draft, context=context)

    def get(self, user, resource_id, *, draft=False, context=None):
        actor = self.members.actor(user)
        self.cleanup_expired()
        with self.store.transaction() as doc:
            return self._get(doc, resource_id, actor, self.now(), draft=draft, context=context)

    def change(self, user, resource_id, data, *, request_id, expected_version, action='save', draft=False, context=None):
        if action not in ({'save_draft', 'publish'} if draft else {'save', 'withdraw'}):
            raise TaskError('invalid_board_action')
        def apply(doc, actor, now):
            value = self._draft(doc, resource_id, actor, now, context) if draft else self._post(doc, resource_id, actor)
            self._context(value, context, draft=draft, write=True)
            if value['created_by'] != actor:
                raise TaskError('forbidden', '只有作者可以修改便笺。', status=403)
            if value.get('committed_post_id'):
                raise TaskError('draft_already_published', '该草稿已发布，请修改原便笺。', status=409)
            if not draft and self._state(value, now) != 'active':
                raise TaskError('board_read_only', '便笺已过期或撤下，只可查看。', status=409)
            check_version(value, expected_version)
            if action == 'withdraw':
                if data:
                    raise TaskError('invalid_board_fields')
                value.update(publication_state='withdrawn', withdrawn_at=now.isoformat())
            else:
                combined = {k: deepcopy(v) for k, v in value.items() if k in FIELDS}
                if not isinstance(data, dict):
                    raise TaskError('invalid_board_fields')
                combined.update(data)
                value.update(self._normalize(doc, actor, combined, now, draft=draft and action != 'publish', publishing=not draft or action == 'publish'))
            value.update(version=value['version'] + 1, updated_at=now.isoformat())
            if draft and action == 'publish':
                post = {k: deepcopy(v) for k, v in value.items() if k not in {'draft_expires_at', 'session_id', 'branch_id', 'user_message_id'}}
                post.update(id='post_' + uuid.uuid4().hex, version=1, publication_state='published', published_at=now.isoformat(), withdrawn_at=None)
                value['committed_post_id'] = post['id']
                doc['posts'][post['id']] = post
                return post, False
            return value, draft
        return self._operation(user, request_id, {'action': action, 'id': resource_id, 'data': data, 'version': expected_version}, apply, context=context)

    def list(self, user, *, cursor=None, limit=30, context=None):
        actor = self.members.actor(user)
        if not 1 <= limit <= 100:
            raise TaskError('invalid_board_filter')
        self._context({}, context)
        self.cleanup_expired()
        with self.store.transaction() as doc:
            now = self.now()
            rows = [p for p in doc['posts'].values() if self._can_read(p, actor) and self._state(p, now) == 'active']
            rows.sort(key=lambda p: (p['published_at'], p['id']), reverse=True)
            if cursor:
                try:
                    stamp, identifier = json.loads(cursor)
                    rows = [p for p in rows if (p['published_at'], p['id']) < (stamp, identifier)]
                except (ValueError, TypeError):
                    raise TaskError('invalid_cursor')
            page = rows[:limit]
            next_cursor = json.dumps([page[-1]['published_at'], page[-1]['id']]) if len(rows) > limit else None
            return {'items': [self._view(doc, p, actor, now, context=context) for p in page], 'next_cursor': next_cursor,
                    'server_now': now.isoformat(), 'revision': doc['revision']}

    def upload(self, user, data):
        actor = self.members.actor(user)
        self.cleanup_expired()
        if len(data) > MAX_IMAGE_BYTES:
            raise TaskError('board_image_too_large', '单张图片不能超过 10MiB。', status=413)
        try:
            with Image.open(BytesIO(data)) as image:
                if image.format not in {'JPEG', 'PNG', 'WEBP'} or image.width * image.height > 40_000_000:
                    raise ValueError()
                image.verify()
            with Image.open(BytesIO(data)) as image:
                image.load()
                image = ImageOps.exif_transpose(image)
                image = image.convert('RGBA' if image.mode == 'RGBA' else 'RGB')
                image.info.clear()
                output = BytesIO()
                image.save(output, format='PNG')
                width, height = image.size
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
            raise TaskError('invalid_board_image', '请选择有效的 JPEG、PNG 或 WebP 图片。')
        encoded = output.getvalue()
        if len(encoded) > 40 * 1024 * 1024:
            raise TaskError('board_image_too_large', '图片解码后过大，请缩小后上传。', status=413)
        # Identical authorized imports have a stable ID, so tool-call retries do
        # not change the publication fingerprint or duplicate assets.
        asset_id = 'asset_' + hashlib.sha256(actor.encode() + b'\0' + encoded).hexdigest()[:32]
        path = self.asset_root / (asset_id + '.png')
        created = False
        try:
            with self.store.transaction() as doc:
                now = self.now()
                referenced = set()
                for post in doc['posts'].values():
                    referenced.update(self._assets(post))
                for draft in doc['drafts'].values():
                    if not draft.get('committed_post_id') and self._date(draft['draft_expires_at']) > now:
                        referenced.update(self._assets(draft))
                for old_id, old in list(doc['assets'].items()):
                    if old_id not in referenced and old_id != asset_id and self._date(old['created_at']) < now - timedelta(days=1):
                        (self.asset_root / (old_id + '.png')).unlink(missing_ok=True)
                        doc['assets'].pop(old_id)
                if asset_id not in doc['assets'] or not path.is_file():
                    path.write_bytes(encoded)
                    path.chmod(0o600)
                    created = True
                    doc['assets'][asset_id] = {'id': asset_id, 'created_by': actor, 'created_at': now.isoformat(),
                                              'width': width, 'height': height, 'mime': 'image/png'}
        except Exception:
            if created:
                path.unlink(missing_ok=True)
            raise
        return {'asset_id': asset_id, 'url': '/api/home/board/assets/' + asset_id, 'width': width, 'height': height}

    def asset(self, user, asset_id):
        actor = self.members.actor(user)
        self.cleanup_expired()
        with self.store.transaction() as doc:
            asset = doc['assets'].get(asset_id)
            if not asset or not re.fullmatch(r'asset_[a-f0-9]{32}', asset_id):
                raise TaskError('board_asset_not_found', status=404)
            posts = [p for p in doc['posts'].values() if asset_id in self._assets(p)]
            allowed = any(self._can_read(p, actor) and self._state(p, self.now()) != 'expired' for p in posts)
            if not posts and asset['created_by'] == actor:
                allowed = True
            if not allowed:
                raise TaskError('board_asset_not_found', status=404)
            path = self.asset_root / (asset_id + '.png')
            if not path.is_file():
                raise TaskError('board_asset_not_found', status=404)
            return path
