"""Task-domain card operations; no chat or presentation-specific persistence."""
from copy import deepcopy
from datetime import timedelta
import json
import uuid

from services.task_access import check_version, require_creator, visible_task
from services.task_card_policy import assert_writable, can_complete_overdue, readonly_reason, temporal_state
from services.task_recurrence import materialize, monday, parse_date, project
from services.task_store import TaskError


class TaskCardsMixin:
    @staticmethod
    def card_time_state(task, occ, now):
        return temporal_state(task, occ, now)['time_state']

    def _card_occurrence(self, doc, task, instance_id, now):
        if not task['actionable']:
            if instance_id:
                raise TaskError('occurrence_not_found', status=404)
            return None
        materialize(doc, task, now.date())
        if not instance_id:
            if task['recurrence']:
                raise TaskError('occurrence_required', '周期卡片必须指定期次。')
            instance_id = task['id'] + ':once'
        aliases = doc.get('occurrence_aliases', {})
        visited = set()
        while instance_id in aliases and instance_id not in visited:
            visited.add(instance_id)
            instance_id = aliases[instance_id]
        occ = doc['occurrences'].get(instance_id)
        if not occ and task['recurrence'] and instance_id.startswith(task['id'] + ':'):
            period = parse_date(instance_id.split(':', 1)[1])
            occ = next((o for o in project(task, period, period + timedelta(days=6)) if o['id'] == instance_id), None)
            if occ:
                occ.pop('projected', None)
                doc['occurrences'][instance_id] = occ
        if not occ or occ['task_id'] != task['id']:
            raise TaskError('occurrence_not_found', status=404)
        return occ

    def _card_private(self, task, context):
        if task['space_type'] == 'personal' and context:
            if context.get('shared'):
                raise TaskError('private_session_required', '请在个人会话中处理私人事项。', status=403)
            if context.get('protect_private_session'):
                context['protect_private_session']()

    def _card_view(self, doc, actor, task, occ, now):
        timing = temporal_state(task, occ, now)
        reason = readonly_reason(task, occ, now)
        creator = task['created_by'] == actor
        fields, actions = [], []
        if reason is None:
            if creator:
                fields = ['title', 'description', 'category', 'temporal_type', 'due_date', 'due_at',
                          'space_type', 'assignee_ids', 'completion_mode', 'recurrence']
                actions += ['save', 'archive']
                if occ:
                    actions += ['cancel', 'skip']
                if task['recurrence']:
                    actions += ['pause']
            if occ and actor in occ['assignee_ids']:
                done = occ['member_progress'][actor]['status'] == 'completed'
                actions.append('reopen' if done else 'complete')
            if task['space_type'] == 'household' and task['actionable'] and not task['assignee_ids']:
                actions.append('claim')
        elif (reason == 'expired' and can_complete_overdue(task, occ) and actor in occ['assignee_ids']
              and occ['member_progress'][actor]['status'] != 'completed'):
            actions = ['complete']
        elif (reason == 'completed' and task['temporal_type'] == 'timed' and occ and actor in occ['assignee_ids']
              and (occ['member_progress'][actor]['status'] == 'completed' or occ.get('legacy_completion_unknown_actor'))):
            actions = ['reopen']
        elif reason == 'paused' and creator:
            actions = ['resume', 'archive']
        return {**timing, 'timezone': self.timezone_name, 'mode': 'saved',
                'resource': {'type': 'family_task', 'id': task['id'], 'instance_id': (occ or {}).get('id')},
                'task': deepcopy(task), 'occurrence': deepcopy(occ), 'revision': doc['revision'],
                'current_member_id': actor, 'members': self._card_members(),
                'read_only': not actions, 'read_only_reason': reason or ('not_permitted' if not actions else None),
                'capabilities': {'editable_fields': fields, 'actions': actions},
                'effective_on': (monday(now.date()) + timedelta(days=7)).isoformat() if task['recurrence'] else None}

    def _card_members(self):
        return [{k: m.get(k) for k in ('member_id', 'display_name', 'status', 'aliases')} for m in self.members.list()]

    def card_get(self, user, task_id, *, instance_id=None, context=None):
        actor = self.members.actor(user)
        with self.store.transaction() as doc:
            now = self.now()
            task = visible_task(doc, task_id, actor, now.date())
            self._card_private(task, context)
            occ = self._card_occurrence(doc, task, instance_id, now)
            result = self._card_view(doc, actor, task, occ, now)
            if context and context.get('read_only_session'):
                result.update(read_only=True, read_only_reason='read_only_session', capabilities={'editable_fields': [], 'actions': []})
            return result

    def card_change(self, user, task_id, *, request_id, expected_task_version, occurrence_id=None,
                    expected_occurrence_version=None, definition_patch=None, occurrence_patch=None,
                    occurrence_action=None, action='save', scope='single', audience_confirmed=False,
                    context=None):
        definition_patch, occurrence_patch = definition_patch or {}, occurrence_patch or {}
        params = dict(action='card_save', task_id=task_id, expected_task_version=expected_task_version,
                      occurrence_id=occurrence_id, expected_occurrence_version=expected_occurrence_version,
                      definition_patch=definition_patch, occurrence_patch=occurrence_patch,
                      occurrence_action=occurrence_action, card_action=action, scope=scope,
                      audience_confirmed=audience_confirmed)
        def apply(doc, actor, now):
            task = visible_task(doc, task_id, actor, now.date())
            self._card_private(task, context)
            occ = self._card_occurrence(doc, task, occurrence_id, now)
            initial = deepcopy({'task': task, 'occurrence': occ})
            check_version(task, expected_task_version)
            operation = (occurrence_action or {}).get('action') or action
            if action not in {'save', 'archive', 'claim', 'pause', 'resume'}:
                raise TaskError('invalid_action')
            assert_writable(task, occ, now, operation)
            view = self._card_view(doc, actor, task, occ, now)
            if action != 'save' and (definition_patch or occurrence_patch or occurrence_action):
                raise TaskError('invalid_card_action', '请先保存修改，再执行其他操作。')
            if occ:
                check_version(occ, (occurrence_action or {}).get('expected_version', expected_occurrence_version))
            if definition_patch:
                require_creator(task, actor)
                assert_writable(task, occ, now, 'update')
                if task['recurrence'] and scope != 'future':
                    raise TaskError('series_scope_required', '系列定义修改需选择从下周起。')
                if not task['recurrence'] and scope != 'single':
                    raise TaskError('invalid_scope')
                patch = {**definition_patch, 'audience_confirmed': audience_confirmed, 'scope': 'future'}
                if patch.get('space_type') == 'personal':
                    self._card_private({**task, 'space_type': 'personal'}, context)
                if patch.get('due_at') and not patch.get('due_date'):
                    from datetime import datetime
                    try:
                        stamp = datetime.fromisoformat(patch['due_at'])
                        if stamp.tzinfo:
                            patch['due_date'] = stamp.astimezone(self.zone).date().isoformat()
                    except (TypeError, ValueError):
                        pass
                # All definitions are validated by the same authority as tools.
                self._change_in_doc(doc, actor, now, task_id, 'update', task['version'], patch=patch)
                if occ and not doc['occurrences'].get(occ['id']):
                    replacement = next((o for o in doc['occurrences'].values() if o['task_id'] == task_id and o.get('source_occurrence_id') == occ['id']), None)
                    if replacement:
                        doc.setdefault('occurrence_aliases', {})[occ['id']] = replacement['id']
                        occ = replacement
                elif occ and initial['task']['recurrence'] and not task['recurrence']:
                    replacement = doc['occurrences'].get(task_id + ':once')
                    if replacement:
                        doc.setdefault('occurrence_aliases', {})[occ['id']] = replacement['id']
                        occ = replacement
                if not task['recurrence'] and task['actionable']:
                    occ = doc['occurrences'].get(task_id + ':once', occ)
            if occurrence_patch:
                if not occ or scope != 'occurrence' or definition_patch:
                    raise TaskError('invalid_occurrence_fields')
                self._change_in_doc(doc, actor, now, task_id, 'update_occurrence', occ['version'], occ['id'], occurrence_patch)
            if occurrence_action:
                state_action = occurrence_action.get('action')
                if not occ or state_action not in {'complete', 'reopen', 'cancel', 'skip'}:
                    raise TaskError('invalid_action')
                self._change_in_doc(doc, actor, now, task_id, state_action, occ['version'], occ['id'])
            elif action != 'save':
                if action not in view['capabilities']['actions']:
                    raise TaskError('forbidden', status=403)
                self._change_in_doc(doc, actor, now, task_id, action, task['version'])
            if not definition_patch and not occurrence_patch and not occurrence_action and action == 'save':
                raise TaskError('no_changes', '没有需要保存的修改。')
            result = self._card_view(doc, actor, task, occ, now)
            result['task_ids'] = [task_id]
            result['changes'] = {'before': initial, 'after': deepcopy({'task': task, 'occurrence': occ})}
            return result
        result = self._mutate(user, request_id, 0, params, apply)
        # Reauthenticate replayed responses in their current chat surface too.
        current = self.card_get(user, task_id, instance_id=result['resource'].get('instance_id'), context=context)
        return {**result, **current}

    def card_references(self, user, task_ids, context, *, instance_id=None):
        refs = []
        for task_id in dict.fromkeys(task_ids):
            detail = self.get(user, task_id)
            task = detail['task']
            selected = instance_id
            if task['actionable'] and not selected:
                if task['recurrence']:
                    candidates = [o for o in [*detail['occurrences'], *detail['preview']]
                                  if o['due_date'] and o['due_date'] >= self.now().date().isoformat()]
                    chosen = min(candidates, key=lambda o: o['due_date']) if candidates else next(iter(detail['occurrences']), None)
                    selected = chosen['id'] if chosen else None
                else:
                    selected = task_id + ':once'
            if task['actionable'] and not selected:
                continue
            from agent_runtime.card_presenter import card_reference
            refs.append(card_reference('task', 'family_task', task_id, selected, context))
        return refs

    def draft_save(self, user, items, invocation, context):
        actor = self.members.actor(user)
        key = json.dumps([context.get('session_id', ''), context.get('branch_id', ''), actor])
        with self.store.transaction() as doc:
            previous = doc['drafts'].get(key, {})
            draft = {'id': previous.get('id') or 'draft_' + uuid.uuid4().hex,
                     'version': previous.get('version', 0) + 1, 'items': deepcopy(items),
                     'invocation': deepcopy(invocation), 'user_id': user['id'],
                     'session_id': context.get('session_id', ''), 'branch_id': context.get('branch_id', ''),
                     'user_message_id': context.get('user_message_id'),
                     'expires_at': (self.now() + timedelta(minutes=30)).isoformat()}
            doc['drafts'][key] = draft
            return deepcopy(draft)

    def _draft_find(self, doc, user, draft_id, context):
        pair = next(((k, d) for k, d in doc['drafts'].items() if d.get('id') == draft_id), None)
        committed = doc.get('draft_commits', {}).get(draft_id)
        draft = pair[1] if pair else (committed or {}).get('draft')
        if (not draft or draft.get('user_id') != user['id'] or not context
                or draft.get('session_id') != context.get('session_id')
                or draft.get('branch_id') != context.get('branch_id')
                or (draft.get('user_message_id') and draft['user_message_id'] not in context.get('active_message_ids', []))):
            raise TaskError('draft_not_found', '草稿已失效或不在当前会话分支。', status=404)
        inv = draft.get('invocation') or {}
        self._card_private({'space_type': inv.get('space_type', 'personal')}, context)
        return (pair[0] if pair else None), draft, committed

    def _draft_view(self, doc, user, draft, now):
        actor = self.members.actor(user)
        inv = draft.get('invocation') or {}
        expires = draft['expires_at']
        for item in draft['items']:
            if item.get('due_date') or item.get('due_at'):
                from datetime import datetime
                day = item.get('due_date') or datetime.fromisoformat(item['due_at']).astimezone(self.zone).date().isoformat()
                timing = temporal_state({'timezone': self.timezone_name, 'due_date': day}, None, now)
                expires = min(expires, timing['valid_until'])
        expired = now.isoformat() >= expires
        return {'mode': 'draft', 'resource': {'type': 'task_draft', 'id': draft['id']},
                'draft': deepcopy(draft), 'members': self._card_members(), 'current_member_id': actor,
                'timezone': self.timezone_name, 'server_now': now.isoformat(), 'time_state': 'expired' if expired else 'draft',
                'valid_until': expires, 'next_transition_at': expires if not expired else None,
                'read_only': expired, 'read_only_reason': 'draft_expired' if expired else None,
                'capabilities': {'editable_fields': [] if expired else ['items', 'space_type', 'temporal_type', 'assignee_ids'],
                                 'actions': [] if expired else ['create']}}

    def draft_get(self, user, draft_id, context):
        with self.store.transaction() as doc:
            now = self.now()
            _key, draft, committed = self._draft_find(doc, user, draft_id, context)
            if committed:
                task = visible_task(doc, committed['task_ids'][0], self.members.actor(user), now.date())
                self._card_private(task, context)
                occ = self._card_occurrence(doc, task, committed['instance_id'], now)
                view = self._card_view(doc, self.members.actor(user), task, occ, now)
                view['additional_cards'] = deepcopy(committed.get('additional_cards', []))
                return view
            return self._draft_view(doc, user, draft, now)

    def draft_commit(self, user, draft_id, *, request_id, expected_version, items,
                     space_type, temporal_type, assignee_ids, completion_mode='all', literal_time_text=False, context=None):
        if space_type not in {'personal', 'household'} or temporal_type not in {'timed', 'undated'}:
            raise TaskError('invalid_task_type')
        def apply(doc, actor, now):
            key, draft, committed = self._draft_find(doc, user, draft_id, context)
            if committed:
                for task_id in committed['task_ids']:
                    visible_task(doc, task_id, actor, now.date())
                return deepcopy(committed['result'])
            view = self._draft_view(doc, user, draft, now)
            if view['read_only']:
                raise TaskError('draft_expired', '草稿已过期，请重新提供事项。', status=409)
            check_version(draft, expected_version)
            self._card_private({'space_type': space_type}, context)
            ids = self.members.validate(assignee_ids)
            invocation = {'command': ('家庭' if space_type == 'household' else '') + ('日程' if temporal_type == 'timed' else '备忘'),
                          'space_type': space_type, 'temporal_type': temporal_type, 'mentions': [{'member_id': i} for i in ids],
                          'actionable': True, 'completion_mode': completion_mode, 'literal_time_text': literal_time_text}
            result = self._create_in_doc(doc, actor, now, items, invocation,
                source={k: draft.get(k) for k in ('session_id', 'branch_id', 'user_message_id')})
            return self._remember_draft_commit(doc, draft, result, actor, now, key=key)
        result = self._mutate(user, request_id, 0, {'action': 'draft_commit', 'draft_id': draft_id,
            'expected_version': expected_version, 'items': items, 'space_type': space_type,
            'temporal_type': temporal_type, 'assignee_ids': assignee_ids, 'completion_mode': completion_mode,
            'literal_time_text': literal_time_text}, apply)
        return {**result, **self.draft_get(user, draft_id, context)}

    def _remember_draft_commit(self, doc, draft, result, actor, now, key=None):
        task = result['tasks'][0]
        occurrence_id = task['id'] + (':' + monday(parse_date(task['starts_on'])).isoformat() if task['recurrence'] else ':once')
        occ = self._card_occurrence(doc, task, occurrence_id, now)
        output = {**self._card_view(doc, actor, task, occ, now), 'task_ids': result['task_ids']}
        from agent_runtime.card_presenter import card_reference
        additional = []
        for other in result['tasks'][1:]:
            oid = other['id'] + (':' + monday(parse_date(other['starts_on'])).isoformat() if other['recurrence'] else ':once')
            additional.append(card_reference('task', 'family_task', other['id'], oid, {'run_id': draft['id']}))
        output['additional_cards'] = additional
        doc.setdefault('draft_commits', {})[draft['id']] = {'draft': deepcopy(draft), 'result': deepcopy(output),
            'task_ids': result['task_ids'], 'instance_id': occurrence_id, 'additional_cards': additional}
        if key:
            doc['drafts'].pop(key, None)
        return output
