"""Authoritative poll/relay rules shared by HTTP, native tools and lifecycle jobs."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import uuid
from services.task_store import TaskError

FIELDS = {'title', 'description', 'participation_deadline_at', 'expires_at', 'participation_duration_hours',
          'retention_duration_hours', 'auto_close', 'notify_creator', 'options', 'multiple', 'min_choices',
          'max_choices', 'allow_change', 'fields', 'capacity', 'required_time_fields'}
DEFAULTS = dict(title='', description='', participation_deadline_at=None, expires_at=None,
                participation_duration_hours=None, retention_duration_hours=None, auto_close=True,
                notify_creator=True, options=[], multiple=False, min_choices=1, max_choices=1,
                allow_change=True, fields=[], capacity=None, required_time_fields=[])


def version(actual, expected):
    if type(expected) is not int or actual != expected:
        raise TaskError('version_conflict', '内容已更新，请重新读取后重试。', status=409)


class FamilyActivityService:
    def __init__(self, store, members, *, timezone_name='Asia/Shanghai', clock=None):
        self.store, self.members, self.timezone_name, self.clock = store, members, timezone_name, clock
        self.store.clock = self.now

    def now(self):
        return (self.clock() if self.clock else datetime.now(timezone.utc)).astimezone(timezone.utc)

    @staticmethod
    def date(value):
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                raise ValueError()
            return parsed.astimezone(timezone.utc)
        except (ValueError, TypeError, AttributeError):
            raise TaskError('invalid_activity_time', '截止时间必须包含时区。')

    def context(self, context=None, row=None, *, write=False, draft=False):
        context, row = context or {}, row or {}
        if write and context.get('read_only_session'):
            raise TaskError('read_only_session', status=403)
        if context.get('session_id'):
            session = context.get('session') or {}
            shared = context.get('shared') or (session.get('sharing') or {}).get('scope', 'private') != 'private'
            if shared or session.get('owner_user_id', context.get('user_id')) != context.get('user_id'):
                raise TaskError('private_session_required', '请在自己的个人对话中操作家庭活动。', status=403)
            if context.get('protect_private_session'):
                context['protect_private_session']()
        if draft and row.get('session_id') and (row['session_id'] != context.get('session_id')
                or row['branch_id'] != context.get('branch_id', 'main')
                or row.get('user_message_id') not in context.get('active_message_ids', [])):
            raise TaskError('activity_not_found', status=404)

    def normalize(self, kind, data, *, publishing=False):
        if not isinstance(data, dict) or set(data) - FIELDS:
            raise TaskError('invalid_activity_fields', '活动包含不支持的字段。')
        value = deepcopy(DEFAULTS)
        value.update(deepcopy(data))
        for field, limit in [('title', 120), ('description', 5000)]:
            if not isinstance(value[field], str) or len(value[field]) > limit:
                raise TaskError('invalid_activity_text', '标题或说明过长。')
            value[field] = value[field].strip()
        for field in ('auto_close', 'notify_creator', 'multiple', 'allow_change'):
            if type(value[field]) is not bool:
                raise TaskError('invalid_activity_rule')
        for field in ('participation_deadline_at', 'expires_at'):
            if value[field] is not None:
                value[field] = self.date(value[field]).isoformat()
        for field in ('participation_duration_hours', 'retention_duration_hours'):
            hours = value[field]
            if hours is not None and (type(hours) not in (int, float) or not math.isfinite(hours) or not 0 < hours <= 876000):
                raise TaskError('invalid_activity_duration')
        if publishing:
            for field, duration in [('participation_deadline_at', 'participation_duration_hours'), ('expires_at', 'retention_duration_hours')]:
                if value[duration] is not None:
                    value[field] = (self.now() + timedelta(hours=value[duration])).isoformat()
                    value[duration] = None
                if value[field] and self.date(value[field]) <= self.now():
                    raise TaskError('activity_time_in_past', '请选择未来的截止时间。')
        if value['participation_deadline_at'] and value['expires_at'] and self.date(value['participation_deadline_at']) > self.date(value['expires_at']):
            raise TaskError('activity_time_order', '存在截止不能早于参与截止。')
        if not isinstance(value['options'], list) or len(value['options']) > 50:
            raise TaskError('invalid_poll_options')
        options = []
        for index, item in enumerate(value['options']):
            item = {'text': item} if isinstance(item, str) else item
            if not isinstance(item, dict) or set(item) - {'id', 'text'} or not isinstance(item.get('text'), str) or not item['text'].strip() or len(item['text']) > 300:
                raise TaskError('invalid_poll_options', '投票选项不能为空。')
            identifier = item.get('id', 'option_' + str(index + 1))
            if not isinstance(identifier, str) or not 1 <= len(identifier) <= 100:
                raise TaskError('invalid_poll_options')
            options.append({'id': identifier, 'text': item['text'].strip()})
        if len({o['id'] for o in options}) != len(options) or len({o['text'] for o in options}) != len(options):
            raise TaskError('duplicate_poll_options', '选项不能重复。')
        value['options'] = options
        if any(type(value[k]) is not int or not 1 <= value[k] <= 50 for k in ('min_choices', 'max_choices')):
            raise TaskError('invalid_poll_limits')
        if not value['multiple']:
            value['min_choices'] = value['max_choices'] = 1
        if value['min_choices'] > value['max_choices'] or (kind == 'poll' and options and value['max_choices'] > len(options)):
            raise TaskError('invalid_poll_limits', '请检查多选数量上下限。')
        if value['capacity'] is not None and (type(value['capacity']) is not int or not 1 <= value['capacity'] <= 100000):
            raise TaskError('invalid_relay_capacity')
        if not isinstance(value['fields'], list) or len(value['fields']) > 12:
            raise TaskError('invalid_relay_fields')
        seen = set()
        for field in value['fields']:
            if (not isinstance(field, dict) or set(field) - {'id', 'label', 'type', 'required'}
                    or not isinstance(field.get('id'), str) or not 1 <= len(field['id']) <= 80
                    or field['id'] in seen or not isinstance(field.get('label'), str)
                    or not 1 <= len(field['label']) <= 120 or field.get('type') not in ('text', 'number')
                    or type(field.get('required')) is not bool):
                raise TaskError('invalid_relay_fields')
            seen.add(field['id'])
        if not isinstance(value['required_time_fields'], list) or any(k not in ('participation_deadline_at', 'expires_at') for k in value['required_time_fields']):
            raise TaskError('invalid_activity_fields')
        missing_times = [({'participation_deadline_at': '参与截止时间', 'expires_at': '存在截止时间'})[k] for k in value['required_time_fields'] if not value[k] and value['participation_duration_hours' if k == 'participation_deadline_at' else 'retention_duration_hours'] is None]
        missing = missing_times + ([] if value['title'] else ['标题']) + (['至少两个投票选项'] if kind == 'poll' and len(options) < 2 else [])
        if publishing and missing:
            raise TaskError('activity_fields_required', '请补充：' + '、'.join(missing))
        value['missing_fields'] = missing
        return value

    def _get(self, doc, identifier, actor, kind, context=None, draft=False):
        row = doc['drafts' if draft else 'activities'].get(identifier)
        if not row or row['kind'] != kind or (draft and row['created_by'] != actor):
            raise TaskError('activity_not_found', '该家庭活动已不可访问。', status=404)
        self.context(context, row, draft=draft)
        if draft and row.get('committed_id'):
            return self._get(doc, row['committed_id'], actor, kind, context)
        return row

    def _receipt(self, doc, actor, request_id, signature):
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 200:
            raise TaskError('request_id_required')
        key = hashlib.sha256((actor + '\0' + request_id).encode()).hexdigest()
        fingerprint = hashlib.sha256(json.dumps(signature, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        old = doc['operations'].get(key)
        if old and old['fingerprint'] != fingerprint:
            raise TaskError('request_id_conflict', status=409)
        return key, fingerprint, old

    def _close(self, doc, row, reason):
        active = {m['member_id'] for m in self.members.list() if m['status'] == 'active'}
        row['completion_member_ids_at_close'] = sorted(set(row['completion_member_ids']) & active)
        row['completion_excluded_member_ids'] = sorted(set(row['completion_member_ids']) - active)
        row.update(state='closed', close_reason=reason, closed_at=self.now().isoformat(), revision=row['revision'] + 1)
        if row['notify_creator'] and reason != 'manual':
            key = row['id'] + ':closed'
            doc['notifications'].setdefault(key, dict(id='activity:' + key, activity_id=row['id'],
                member_id=row['created_by'], created_at=row['closed_at'], read_at=None, status='pending', attempts=0, next_at=0))

    def _advance(self, doc):
        active = {m['member_id'] for m in self.members.list() if m['status'] == 'active'}
        for row in doc['activities'].values():
            if row['state'] != 'open':
                continue
            participants = {p['member_id'] for p in doc['participations'].values() if p['activity_id'] == row['id'] and p['active']}
            target = set(row['completion_member_ids']) & active
            reason = ('deadline' if row['participation_deadline_at'] and self.now() >= self.date(row['participation_deadline_at']) else
                      'capacity' if row['kind'] == 'relay' and row['capacity'] and len(participants) >= row['capacity'] else
                      'all_completed' if row['auto_close'] and target and target <= participants else None)
            if reason:
                self._close(doc, row, reason)

    def cleanup_expired(self):
        with self.store.transaction() as doc:
            self._advance(doc)
            active = {m['member_id'] for m in self.members.list() if m['status'] == 'active'}
            for event in doc['notifications'].values():
                if event['member_id'] not in active:
                    event['status'] = 'cancelled'
        self.store.cleanup_backups()

    def _prepare(self, user, context=None, write=False):
        actor = self.members.actor(user)
        self.context(context, write=write)
        self.cleanup_expired()
        return actor

    def view(self, doc, row, actor, context=None):
        draft = row['state'] == 'draft'
        participants = sorted([deepcopy(p) for p in doc['participations'].values()
                               if p['activity_id'] == row['id'] and p['active']], key=lambda p: (p.get('sequence', 0), p['member_id']))
        own = doc['participations'].get(row['id'] + ':' + actor)
        creator, opened = row['created_by'] == actor, row['state'] == 'open'
        actions = (['save_draft', 'publish', 'delete'] if draft and creator else
                   (['save', 'close', 'delete'] if opened and creator else ['delete'] if creator else []))
        if opened:
            if not own or not own['active'] or row['kind'] == 'relay' or row['allow_change']:
                actions += ['participate']
            if own and own['active'] and (row['kind'] == 'relay' or row['allow_change']):
                actions += ['withdraw']
        editable = sorted(FIELDS) if creator and (draft or opened) else []
        if not draft and any(p['activity_id'] == row['id'] for p in doc['participations'].values()):
            frozen = {'title', 'options', 'multiple', 'min_choices', 'max_choices', 'allow_change', 'fields'}
            editable = [key for key in editable if key not in frozen]
        if (context or {}).get('read_only_session'):
            actions, editable = [], []
        cutoffs = [row.get('expires_at'), row.get('draft_expires_at') if draft else None,
                   row.get('participation_deadline_at') if opened else None]
        cutoffs = [value for value in cutoffs if value]
        public = {k: deepcopy(v) for k, v in row.items() if k not in ('session_id', 'branch_id', 'user_message_id', 'committed_id')}
        if row['kind'] == 'poll':
            public['counts'] = {o['id']: sum(o['id'] in p.get('option_ids', []) for p in participants) for o in row['options']}
        return dict(resource={'type': 'family_' + row['kind'] + ('_draft' if draft else ''), 'id': row['id']},
                    mode='draft' if draft else 'saved', activity=public, participants=participants,
                    participation_version=own['version'] if own else 0, own_participation=deepcopy(own) if own and own['active'] else None,
                    server_now=self.now().isoformat(), timezone=self.timezone_name,
                    valid_until=row.get('draft_expires_at') if draft else row['expires_at'],
                    next_transition_at=min(cutoffs) if cutoffs else None, read_only=not opened and not draft,
                    read_only_reason=None if opened or draft else 'closed', current_member_id=actor,
                    members=[{k: m.get(k) for k in ('member_id', 'display_name', 'status')} for m in self.members.list()],
                    capabilities={'editable_fields': editable, 'actions': actions})

    def create(self, user, kind, data, *, request_id, draft=False, context=None):
        if kind not in ('poll', 'relay'):
            raise TaskError('invalid_activity_kind')
        actor = self._prepare(user, context, True)
        with self.store.transaction() as doc:
            key, fingerprint, old = self._receipt(doc, actor, request_id, ['create', kind, data, draft])
            if old:
                return self.view(doc, self._get(doc, old['id'], actor, kind, context, old['draft']), actor)
            normalized = self.normalize(kind, data, publishing=not draft)
            identifier = ('draft_' if draft else kind + '_') + uuid.uuid4().hex
            row = dict(**normalized, id=identifier, kind=kind, created_by=actor, state='draft' if draft else 'open',
                       version=1, revision=1, next_sequence=1, close_reason=None, closed_at=None,
                       created_at=self.now().isoformat(), published_at=None if draft else self.now().isoformat(),
                       completion_member_ids=[m['member_id'] for m in self.members.list() if m['status'] == 'active'])
            if draft:
                ctx = context or {}
                row.update(draft_expires_at=(self.now() + timedelta(days=7)).isoformat(),
                           session_id=ctx.get('session_id'), branch_id=ctx.get('branch_id', 'main'), user_message_id=ctx.get('user_message_id'))
            doc['drafts' if draft else 'activities'][identifier] = row
            if not draft:
                doc['publications'][identifier] = {'activity_id': identifier, 'published_at': row['published_at']}
            doc['operations'][key] = dict(fingerprint=fingerprint, id=identifier, draft=draft)
            return self.view(doc, row, actor)

    def get(self, user, kind, identifier, *, draft=False, context=None):
        actor = self._prepare(user, context)
        with self.store.transaction() as doc:
            self._advance(doc)
            return self.view(doc, self._get(doc, identifier, actor, kind, context, draft), actor, context)

    def list(self, user, kind=None, *, context=None):
        actor = self._prepare(user, context)
        with self.store.transaction() as doc:
            self._advance(doc)
            return [self.view(doc, row, actor, context) for row in sorted(doc['activities'].values(), key=lambda r: (r['published_at'], r['id']), reverse=True)
                    if not kind or row['kind'] == kind]

    def change(self, user, kind, identifier, action, *, data=None, request_id, expected_version=None,
               participation_version=None, draft=False, context=None):
        data = data or {}
        actor = self._prepare(user, context, True)
        with self.store.transaction() as doc:
            self._advance(doc)
            key, fingerprint, old = self._receipt(doc, actor, request_id, [kind, identifier, action, data, expected_version, participation_version, draft])
            if old:
                if action == 'delete':
                    return self.deleted_view(identifier, kind)
                return self.view(doc, self._get(doc, old['id'], actor, kind, context, old['draft']), actor)
            row = self._get(doc, identifier, actor, kind, context, draft)
            if draft and row['state'] != 'draft':
                raise TaskError('draft_already_published', status=409)
            if action in ('save', 'save_draft', 'publish', 'close', 'delete'):
                if actor != row['created_by']:
                    raise TaskError('forbidden', '仅创建者可以管理活动。', status=403)
                version(row['version'], expected_version)
                if action == 'delete':
                    self.store.destroy(doc, identifier)
                    doc['operations'][key] = dict(fingerprint=fingerprint, id=identifier, draft=draft)
                    return self.deleted_view(identifier, kind)
                if row['state'] not in ('open', 'draft'):
                    raise TaskError('activity_closed', '活动已结束，不能重新开放。', status=409)
                if action == 'close':
                    if draft:
                        raise TaskError('invalid_activity_action')
                    self._close(doc, row, 'manual')
                else:
                    if (draft and action not in ('save_draft', 'publish')) or (not draft and action != 'save'):
                        raise TaskError('invalid_activity_action')
                    if set(data) - FIELDS:
                        raise TaskError('invalid_activity_fields')
                    normalized = self.normalize(kind, {**{k: row[k] for k in FIELDS}, **data}, publishing=not draft or action == 'publish')
                    has_history = any(p['activity_id'] == identifier for p in doc['participations'].values())
                    if has_history and any(normalized[k] != row[k] for k in ('title', 'options', 'multiple', 'min_choices', 'max_choices', 'allow_change', 'fields')):
                        raise TaskError('activity_definition_frozen', '已有参与记录，不能更改题目或参与规则。')
                    count = sum(p['activity_id'] == identifier and p['active'] for p in doc['participations'].values())
                    if kind == 'relay' and normalized['capacity'] is not None and normalized['capacity'] < count:
                        raise TaskError('capacity_below_participants')
                    row.update(normalized, version=row['version'] + 1, revision=row['revision'] + 1)
                    if action == 'publish':
                        new_id = kind + '_' + uuid.uuid4().hex
                        published = {k: deepcopy(v) for k, v in row.items() if k not in ('session_id', 'branch_id', 'user_message_id', 'draft_expires_at')}
                        published.update(id=new_id, state='open', published_at=self.now().isoformat(),
                                         completion_member_ids=[m['member_id'] for m in self.members.list() if m['status'] == 'active'])
                        doc['activities'][new_id] = published
                        doc['publications'][new_id] = {'activity_id': new_id, 'published_at': published['published_at']}
                        # Committed drafts retain only identity/context, never a second content copy.
                        for field in FIELDS:
                            row.pop(field, None)
                        row['committed_id'] = new_id
                        row = published
            elif action in ('participate', 'withdraw'):
                if draft or row['state'] != 'open':
                    raise TaskError('activity_closed', '活动已结束。', status=409)
                member_key = identifier + ':' + actor
                own = doc['participations'].get(member_key)
                version(own['version'] if own else 0, participation_version)
                if own and own['active'] and kind == 'poll' and not row['allow_change']:
                    raise TaskError('vote_change_forbidden', '该投票不允许改票或撤票。')
                participation = dict(activity_id=identifier, member_id=actor, version=(own['version'] if own else 0) + 1,
                                     active=action == 'participate', updated_at=self.now().isoformat())
                if action == 'withdraw':
                    if not own or not own['active']:
                        raise TaskError('participation_not_found')
                    participation['sequence'] = own.get('sequence', 0)
                elif kind == 'poll':
                    ids = data.get('option_ids')
                    if (set(data) != {'option_ids'} or not isinstance(ids, list) or any(not isinstance(v, str) for v in ids)
                            or len(set(ids)) != len(ids) or not row['min_choices'] <= len(ids) <= row['max_choices']
                            or not set(ids) <= {o['id'] for o in row['options']}):
                        raise TaskError('invalid_vote', '请选择符合数量要求的有效选项。')
                    participation['option_ids'] = ids
                else:
                    values = data.get('values')
                    fields = row['fields'] or [{'id': 'content', 'label': '接龙内容', 'type': 'text', 'required': True}]
                    if set(data) != {'values'} or not isinstance(values, dict) or set(values) - {f['id'] for f in fields}:
                        raise TaskError('invalid_relay_entry')
                    for field in fields:
                        value = values.get(field['id'])
                        if value is None or value == '' or (isinstance(value, str) and not value.strip()):
                            if field['required']:
                                raise TaskError('relay_field_required', '请填写：' + field['label'])
                        elif (field['type'] == 'text' and (not isinstance(value, str) or len(value) > 2000)) or (field['type'] == 'number' and (type(value) not in (int, float) or not math.isfinite(value))):
                            raise TaskError('invalid_relay_entry', '请检查字段：' + field['label'])
                    participation['values'] = values
                    participation['sequence'] = own['sequence'] if own and own['active'] else row['next_sequence']
                    if not own or not own['active']:
                        row['next_sequence'] += 1
                doc['participations'][member_key] = participation
                row['revision'] += 1
            else:
                raise TaskError('invalid_activity_action')
            self._advance(doc)
            doc['operations'][key] = dict(fingerprint=fingerprint, id=row['id'], draft=row['state'] == 'draft')
            return self.view(doc, row, actor)

    def deleted_view(self, identifier, kind):
        return dict(resource={'type': 'family_' + kind, 'id': identifier}, mode='saved', destroyed=True,
                    server_now=self.now().isoformat(), valid_until=None, next_transition_at=None,
                    read_only=True, read_only_reason='destroyed', capabilities={'actions': [], 'editable_fields': []})

    def notifications(self, user):
        actor = self._prepare(user)
        with self.store.transaction() as doc:
            return [dict(id=e['id'], kind='family_activity', title='家庭活动已结束', body='点击查看结果。',
                         created_at=e['created_at'], read_at=e['read_at'], recipients=[user['id']],
                         url='/home?panel=board&activity=' + e['activity_id'], source_type='family_activity')
                    for e in doc['notifications'].values() if e['member_id'] == actor]

    def mark_read(self, user, identifier=None):
        actor = self._prepare(user)
        with self.store.transaction() as doc:
            matches = [e for e in doc['notifications'].values() if e['member_id'] == actor and (identifier is None or e['id'] == identifier)]
            if identifier and not matches:
                raise TaskError('notification_not_found', status=404)
            for event in matches:
                event['read_at'] = self.now().isoformat()
        return {'ok': True}
