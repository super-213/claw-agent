"""One authority for chat, HTTP, recurrence, progress and permissions."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
import uuid
from zoneinfo import ZoneInfo

from services.task_access import currently_assigned, can_read, check_version, require_creator, visible_task
from services.task_commands import TIME_TEXT, COMMANDS
from services.task_recurrence import materialize, monday, occurrence, definition_snapshot, parse_date, project, validate_rule
from services.task_store import TaskError


class FamilyTaskService:
    def __init__(self, store, members, *, timezone_name='Asia/Shanghai', clock=None):
        self.store, self.members = store, members
        self.timezone_name = timezone_name
        self.zone = ZoneInfo(timezone_name)
        self.clock = clock or (lambda: datetime.now(self.zone))

    def now(self):
        return self.clock().astimezone(self.zone)

    def _envelope(self, doc, now, **data):
        return {'as_of': now.isoformat(), 'timezone': self.timezone_name,
                'revision': doc['revision'], **data}

    def _mutate(self, user, request_id, operation_index, params, fn):
        actor = self.members.actor(user)
        if not isinstance(request_id, str) or not request_id or len(request_id) > 200:
            raise TaskError('request_id_required')
        if not isinstance(operation_index, int) or isinstance(operation_index, bool) or operation_index < 0:
            raise TaskError('invalid_operation_index')
        now = self.now()
        fingerprint = hashlib.sha256(json.dumps(params, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        key = json.dumps([user['id'], request_id, operation_index])
        with self.store.transaction() as doc:
            previous = doc['operations'].get(key)
            if previous:
                if previous['fingerprint'] != fingerprint:
                    raise TaskError('idempotency_conflict', status=409)
                # A retry is never a permission bypass after reassignment.
                for task_id in previous['result'].get('task_ids', []):
                    visible_task(doc, task_id, actor, now.date())
                return deepcopy(previous['result'])
            result = fn(doc, actor, now)
            result = self._envelope(doc, now, **result)
            result['revision'] = doc['revision'] + 1
            result['task_changed'] = {'type': 'task_changed', 'task_ids': result.get('task_ids', []),
                                      'revision': result['revision']}
            doc['events'].append({'actor': actor, 'at': now.isoformat(), 'task_ids': result.get('task_ids', []),
                                  'action': params['action'], 'revision': result['revision']})
            doc['operations'][key] = {'fingerprint': fingerprint, 'result': deepcopy(result), 'at': now.isoformat()}
            return result

    def _validate_definition(self, value, *, allow_time_text=False):
        if not isinstance(value.get('title'), str) or not value['title'].strip() or len(value['title']) > 500:
            raise TaskError('invalid_title')
        if value.get('temporal_type') not in {'timed', 'undated'} or value.get('space_type') not in {'personal', 'household'}:
            raise TaskError('invalid_task_type')
        if not isinstance(value.get('actionable'), bool):
            raise TaskError('invalid_actionable')
        rule = value.get('recurrence')
        validate_rule(rule)
        for field in ('due_date', 'starts_on'):
            if value.get(field):
                parse_date(value[field])
        if value.get('due_at'):
            try:
                timestamp = datetime.fromisoformat(value['due_at'])
                if not timestamp.tzinfo:
                    raise ValueError()
            except (ValueError, TypeError) as exc:
                raise TaskError('invalid_due_at') from exc
            if value.get('due_date') != timestamp.astimezone(self.zone).date().isoformat():
                raise TaskError('date_time_conflict')
        if value['temporal_type'] == 'undated':
            if any(value.get(k) for k in ('due_date', 'due_at', 'recurrence', 'starts_on')):
                raise TaskError('undated_has_date')
            if not allow_time_text and TIME_TEXT.search(value['title'] + ' ' + value.get('description', '')):
                raise TaskError('memo_time_choice_required', '文字含时间，请选择转为日程或仅作为文字保存。', draft=value)
        elif not value['actionable']:
            raise TaskError('timed_requires_actionable')
        elif not value.get('due_date') and not rule:
            raise TaskError('schedule_date_required', '日程需要日期或每周规则。', draft=value)
        if value.get('completion_mode') not in ({'all', 'any'} if value['actionable'] else {'all', 'any', None}):
            raise TaskError('invalid_completion_mode')

    def create(self, user, items, invocation, *, request_id, operation_index=0, source=None):
        if not invocation:
            raise TaskError('explicit_selection_required', '请选择个人/家庭空间及日程/备忘。', draft=items)
        if not isinstance(invocation, dict) or COMMANDS.get(invocation.get('command')) != (invocation.get('space_type'), invocation.get('temporal_type')):
            raise TaskError('invalid_invocation')
        mentions = invocation.get('mentions', [])
        if not isinstance(mentions, list) or any(not isinstance(m, dict) or not isinstance(m.get('member_id'), str) for m in mentions):
            raise TaskError('invalid_mentions')
        if not isinstance(items, list) or not items or len(items) > 100:
            raise TaskError('invalid_batch')
        allowed = {'title', 'description', 'category', 'due_date', 'due_at', 'recurrence', 'starts_on',
                   'space_type', 'temporal_type', 'assignee_ids', 'actionable', 'completion_mode'}
        def apply(doc, actor, now):
            ids = self.members.validate([m['member_id'] for m in invocation.get('mentions', [])])
            created = []
            for item in items:
                if not isinstance(item, dict) or set(item) - allowed:
                    raise TaskError('invalid_task_fields')
                data = deepcopy(item)
                for field in ('space_type', 'temporal_type', 'actionable', 'completion_mode'):
                    selected = invocation.get(field, 'all' if field == 'completion_mode' else True if field == 'actionable' else None)
                    if field in data and data[field] != selected:
                        raise TaskError('invocation_conflict')
                    data[field] = selected
                expected_ids = ids or ([actor] if data['space_type'] == 'personal' else [])
                if 'assignee_ids' in data and data['assignee_ids'] != expected_ids:
                    raise TaskError('invocation_conflict')
                self._validate_definition(data, allow_time_text=invocation.get('literal_time_text') is True)
                task_id = 'task_' + uuid.uuid4().hex
                household_id = self.members.home.household().get('id', 'household_default')
                task = {**data, 'id': task_id, 'household_id': household_id,
                        'space_owner_id': actor if data['space_type'] == 'personal' else household_id,
                        'space_id': 'personal:' + actor if data['space_type'] == 'personal' else 'household:' + household_id,
                        'created_by': actor, 'assignee_ids': expected_ids if data['actionable'] else [],
                        'related_member_ids': ids if not data['actionable'] else [],
                        'visibility': 'participants' if data['space_type'] == 'personal' else 'household',
                        'completion_mode': data['completion_mode'] if data['actionable'] else None,
                        'title': data['title'].strip(), 'description': data.get('description', ''),
                        'category': data.get('category'), 'due_date': data.get('due_date'), 'due_at': data.get('due_at'),
                        'recurrence': data.get('recurrence'), 'starts_on': data.get('starts_on') or
                        ((data.get('due_date') or now.date().isoformat()) if data.get('recurrence') else None),
                        'timezone': self.timezone_name, 'lifecycle': 'active', 'version': 1, 'rule_revision': 1,
                        'created_at': now.isoformat(), 'updated_at': now.isoformat(), 'source': source or {}}
                if task['recurrence']:
                    task['definition_history'] = [{'effective_on': monday(parse_date(task['starts_on'])).isoformat(),
                                                   'definition': definition_snapshot(task)}]
                doc['tasks'][task_id] = task
                materialize(doc, task, now.date())
                created.append(deepcopy(task))
            return {'tasks': created, 'task_ids': [t['id'] for t in created]}
        return self._mutate(user, request_id, operation_index, {'action': 'create', 'items': items, 'invocation': invocation}, apply)

    def _rows(self, doc, actor, now, filters):
        tasks = [t for t in doc['tasks'].values() if can_read(t, actor, now.date())]
        view = filters.get('view', 'mine')
        if view not in {'mine', 'own', 'assigned', 'delegated', 'household', 'visible'}:
            raise TaskError('invalid_view')
        if view == 'household':
            tasks = [t for t in tasks if t['visibility'] == 'household']
        elif view == 'delegated':
            tasks = [t for t in tasks if t['created_by'] == actor and any(m != actor for m in t['assignee_ids'])]
        elif view == 'own':
            tasks = [t for t in tasks if t['space_type'] == 'personal' and t['space_owner_id'] == actor]
        elif view == 'assigned':
            tasks = [t for t in tasks if currently_assigned(t, actor, now.date()) and t['created_by'] != actor]
        elif view == 'mine':
            tasks = [t for t in tasks if currently_assigned(t, actor, now.date()) or actor in t.get('related_member_ids', [])
                     or (not t['actionable'] and t['created_by'] == actor)]
        complete = True
        rows = []
        today = now.date()
        for task in tasks:
            if any(filters.get(k) not in (None, '') and filters[k] != task.get(k) for k in ('space_type', 'temporal_type', 'actionable', 'lifecycle')):
                continue
            if not filters.get('lifecycle') and task['lifecycle'] == 'archived':
                continue
            if filters.get('assignee_id') and filters['assignee_id'] not in task['assignee_ids']:
                continue
            if filters.get('recurring') is not None and bool(task['recurrence']) != filters['recurring']:
                continue
            if filters.get('query') and filters['query'].casefold() not in (task['title'] + task['description']).casefold():
                continue
            complete = materialize(doc, task, today) and complete
            occurrences = [o for o in doc['occurrences'].values() if o['task_id'] == task['id']]
            if task['recurrence'] and filters.get('due_to') and parse_date(filters['due_to']) > today:
                existing = {o['id'] for o in occurrences}
                occurrences += [o for o in project(task, today, parse_date(filters['due_to'])) if o['id'] not in existing]
            if not task['actionable']:
                occurrences = [None]
            for occ in occurrences:
                if occ and filters.get('current_only') and task['recurrence'] and occ['period_key'] != monday(today).isoformat():
                    continue
                due = occ.get('due_date') if occ else None
                status = occ['status'] if occ else 'information'
                if filters.get('status') and status != filters['status']:
                    continue
                if filters.get('due_from') and (not due or due < filters['due_from']):
                    continue
                if filters.get('due_to') and (not due or due > filters['due_to']):
                    continue
                if filters.get('undated') and due:
                    continue
                rows.append({'task': deepcopy(task), 'occurrence': deepcopy(occ),
                             'overdue': bool(occ and status == 'open' and due and due < today.isoformat()),
                             'assignee_unavailable': [m for m in task['assignee_ids'] if m not in
                                {r['member_id'] for r in self.members.list() if r['status'] == 'active'}]})
        rows.sort(key=lambda row: ((row['occurrence'] or {}).get('due_date') or '9999', row['task']['created_at'],
                                   (row['occurrence'] or {}).get('id', row['task']['id'])))
        return rows, complete

    def list(self, user, **filters):
        actor, now = self.members.actor(user), self.now()
        if filters.get('status') is None and filters.get('actionable') is not False:
            filters['status'] = 'open'
        for field in ('due_from', 'due_to'):
            if filters.get(field):
                parse_date(filters[field])
        with self.store.transaction() as doc:
            before = deepcopy(doc)
            rows, complete = self._rows(doc, actor, now, filters)
            try:
                cursor = int(filters.get('cursor') or 0)
                limit = max(1, min(int(filters.get('limit') or 50), 200))
                if cursor < 0:
                    raise ValueError()
            except (ValueError, TypeError) as exc:
                raise TaskError('invalid_cursor') from exc
            result = self._envelope(doc, now, items=rows[cursor:cursor + limit],
                total=len(rows) if complete else None, history_complete=complete,
                next_cursor=str(cursor + limit) if cursor + limit < len(rows) else None,
                history_next_cursor=None if complete else 'continue', today=now.date().isoformat())
            result['revision'] += int(before != doc)
            return result

    def summary(self, user, **filters):
        actor, now = self.members.actor(user), self.now()
        with self.store.transaction() as doc:
            before = deepcopy(doc)
            rows, complete = self._rows(doc, actor, now, filters)
            today = now.date().isoformat()
            counts = {'open': 0, 'completed': 0, 'undated': 0, 'today': 0, 'overdue': 0, 'information': 0, 'unclaimed': 0}
            for row in rows:
                task, occ = row['task'], row['occurrence']
                if occ is None:
                    counts['information'] += 1
                elif occ['status'] in counts:
                    counts[occ['status']] += 1
                    if occ['status'] == 'open':
                        counts['undated'] += int(not occ['due_date'])
                        counts['today'] += int(occ['due_date'] == today)
                        counts['overdue'] += int(row['overdue'])
                        counts['unclaimed'] += int(not occ['assignee_ids'])
            if not complete:
                counts['overdue'] = None
            return {**self._envelope(doc, now, counts=counts, history_complete=complete),
                    'revision': doc['revision'] + int(before != doc)}

    def get(self, user, task_id):
        actor, now = self.members.actor(user), self.now()
        with self.store.transaction() as doc:
            before = deepcopy(doc)
            task = visible_task(doc, task_id, actor, now.date())
            complete = materialize(doc, task, now.date())
            return {**self._envelope(doc, now), 'task': deepcopy(task),
                    'occurrences': deepcopy([o for o in doc['occurrences'].values() if o['task_id'] == task_id]),
                    'events': deepcopy([e for e in doc['events'] if task_id in e['task_ids']]),
                    'preview': project(task, max(monday(now.date()) + timedelta(days=7), monday(parse_date(task['starts_on']))) if task['recurrence'] else now.date(),
                        max(monday(now.date()) + timedelta(days=7), monday(parse_date(task['starts_on']))) + timedelta(days=6) if task['recurrence'] else now.date()),
                    'history_complete': complete, 'revision': doc['revision'] + int(before != doc)}

    def change(self, user, task_id, action, *, expected_version, request_id, operation_index=0,
               occurrence_id=None, patch=None):
        patch = patch or {}
        def apply(doc, actor, now):
            task = visible_task(doc, task_id, actor, now.date())
            materialize(doc, task, now.date())
            if occurrence_id:
                occ = doc['occurrences'].get(occurrence_id)
                if not occ and task['recurrence'] and occurrence_id.startswith(task_id + ':'):
                    period = parse_date(occurrence_id.split(':', 1)[1])
                    candidates = project(task, period, period + timedelta(days=6))
                    occ = next((o for o in candidates if o['id'] == occurrence_id), None)
                    if occ:
                        occ.pop('projected', None)
                        doc['occurrences'][occurrence_id] = occ
                if not occ or occ['task_id'] != task_id:
                    raise TaskError('occurrence_not_found', status=404)
                check_version(occ, expected_version)
                if not task['actionable']:
                    raise TaskError('information_not_completable')
                if action in {'complete', 'reopen'}:
                    if actor not in occ['assignee_ids']:
                        raise TaskError('forbidden', '先认领或由负责人完成自己的份额。', status=403)
                    if occ['status'] in {'cancelled', 'skipped'} or task['lifecycle'] == 'archived':
                        raise TaskError('invalid_transition')
                    progress = occ['member_progress'][actor]
                    if progress['status'] == ('completed' if action == 'complete' else 'open') and not (action == 'reopen' and occ.get('legacy_completion_unknown_actor')):
                        return {'task': deepcopy(task), 'occurrence': deepcopy(occ), 'task_ids': [task_id]}
                    if action == 'reopen' and occ.get('legacy_completion_unknown_actor'):
                        occ['legacy_completion_unknown_actor'] = False
                        occ['legacy_history_note'] = '旧记录曾完成，原完成者未知；现已撤销完成。'
                    progress.update(status='completed' if action == 'complete' else 'open',
                                    completed_by=actor if action == 'complete' else None,
                                    completed_at=now.isoformat() if action == 'complete' else None)
                    done = [m for m, p in occ['member_progress'].items() if p['status'] == 'completed']
                    completed = bool(done) and (occ['completion_mode'] == 'any' or len(done) == len(occ['assignee_ids']))
                    occ.update(status='completed' if completed else 'open', completed_by=done if completed else None,
                               completed_at=now.isoformat() if completed else None)
                elif action in {'skip', 'cancel'}:
                    if occ['status'] != 'open':
                        raise TaskError('invalid_transition')
                    require_creator(task, actor)
                    occ['status'] = 'skipped' if action == 'skip' else 'cancelled'
                    occ['reason'] = patch.get('reason', '')
                elif action == 'update_occurrence':
                    if occ['status'] != 'open':
                        raise TaskError('invalid_transition')
                    require_creator(task, actor)
                    if set(patch) - {'title', 'due_date', 'due_at'}:
                        raise TaskError('invalid_occurrence_fields')
                    if task['temporal_type'] == 'undated' and (patch.get('due_date') or patch.get('due_at')):
                        raise TaskError('undated_has_date')
                    candidate = {**task, 'due_date': occ['due_date'], 'due_at': occ['due_at'], **patch}
                    self._validate_definition(candidate, allow_time_text=True)
                    for key, value in patch.items():
                        occ['title_snapshot' if key == 'title' else key] = value
                else:
                    raise TaskError('invalid_action')
                occ['version'] += 1
                result = {'task': deepcopy(task), 'occurrence': deepcopy(occ)}
            else:
                check_version(task, expected_version)
                if action == 'claim':
                    if task['space_type'] != 'household' or task['assignee_ids'] or not task['actionable'] or task['lifecycle'] != 'active':
                        raise TaskError('not_claimable', status=409)
                    task['assignee_ids'] = [actor]
                    for occ in doc['occurrences'].values():
                        if occ['task_id'] == task_id and occ['status'] == 'open' and not occ['assignee_ids']:
                            occ['assignee_ids'] = [actor]
                            occ['member_progress'] = {actor: {'status': 'open', 'completed_by': None, 'completed_at': None}}
                            occ['version'] += 1
                elif action == 'leave':
                    if actor not in task['assignee_ids'] or not task['recurrence'] or not patch.get('reason'):
                        raise TaskError('invalid_participation_change')
                    effective_on = (monday(now.date()) + timedelta(days=7)).isoformat()
                    task.setdefault('definition_history', [{'effective_on': monday(parse_date(task['starts_on'])).isoformat(), 'definition': definition_snapshot(task)}])
                    task['assignee_ids'].remove(actor)
                    task.setdefault('former_assignees_until', {})[actor] = effective_on
                    task['definition_history'].append({'effective_on': effective_on, 'definition': definition_snapshot(task)})
                    task.setdefault('participation_history', []).append({'member_id': actor, 'effective_on':
                        (monday(now.date()) + timedelta(days=7)).isoformat(), 'reason': patch['reason']})
                else:
                    require_creator(task, actor)
                    if action == 'update':
                        self._update(doc, task, patch, actor, now)
                    elif action == 'pause' and task['recurrence'] and task['lifecycle'] == 'active':
                        task.update(lifecycle='paused', paused_on=now.date().isoformat())
                    elif action == 'resume' and task['lifecycle'] == 'paused':
                        start = (monday(parse_date(task['paused_on'])) + timedelta(days=7)).isoformat()
                        end = monday(now.date()).isoformat()
                        if start < end:
                            task.setdefault('paused_periods', []).append([start, end])
                        task['cursor'] = end
                        task['lifecycle'] = 'active'
                    elif action == 'archive':
                        task['lifecycle'] = 'archived'
                        for occ in doc['occurrences'].values():
                            if occ['task_id'] == task_id and occ['status'] == 'open':
                                occ.update(status='cancelled', reason=patch.get('reason', '系列已停止或记录已归档'), version=occ['version'] + 1)
                    else:
                        raise TaskError('invalid_transition')
                task['version'] += 1
                task['updated_at'] = now.isoformat()
                materialize(doc, task, now.date())
                result = {'task': deepcopy(task)}
            return {**result, 'task_ids': [task_id]}
        return self._mutate(user, request_id, operation_index,
                            {'action': action, 'task_id': task_id, 'occurrence_id': occurrence_id,
                             'expected_version': expected_version, 'patch': patch}, apply)

    def _update(self, doc, task, patch, actor, now):
        allowed = {'title', 'description', 'category', 'due_date', 'due_at', 'recurrence', 'starts_on',
                   'space_type', 'temporal_type', 'assignee_ids', 'related_member_ids', 'completion_mode',
                   'scope', 'audience_confirmed', 'literal_time_text'}
        if set(patch) - allowed or patch.get('scope', 'future') != 'future':
            raise TaskError('invalid_task_fields')
        if patch.get('space_type', task['space_type']) != task['space_type'] and not patch.get('audience_confirmed'):
            raise TaskError('audience_confirmation_required', '移动空间会改变可见成员，请明确确认。')
        candidate = {**task, **{k: v for k, v in patch.items() if k not in {'scope', 'audience_confirmed', 'literal_time_text'}}}
        for field in ('assignee_ids', 'related_member_ids'):
            if field in patch:
                self.members.validate(patch[field])
        self._validate_definition(candidate, allow_time_text=patch.get('literal_time_text', False))
        old_rule = task['recurrence']
        previous = deepcopy(task)
        task.update(candidate)
        task['space_owner_id'] = actor if task['space_type'] == 'personal' else task['household_id']
        task['space_id'] = task['space_type'] + ':' + task['space_owner_id']
        task['visibility'] = 'participants' if task['space_type'] == 'personal' else 'household'
        if old_rule != task['recurrence']:
            task['rule_revision'] += 1
            task['starts_on'] = task.get('starts_on') or task.get('due_date') or now.date().isoformat()
            if not old_rule and task['recurrence']:
                old = doc['occurrences'].pop(task['id'] + ':once', None)
                period = monday(parse_date((old or {}).get('due_date') or now.date().isoformat()))
                replacement = occurrence(task, period)
                if old:
                    replacement.update({k: old[k] for k in ('status', 'member_progress', 'completed_by', 'completed_at')})
                    replacement['version'] = old['version'] + 1
                    replacement['source_occurrence_id'] = old['id']
                doc['occurrences'][replacement['id']] = replacement
            elif old_rule and not task['recurrence']:
                # Keep completed history; cancel outstanding periods before creating one single instance.
                for occ in doc['occurrences'].values():
                    if occ['task_id'] == task['id'] and occ['status'] == 'open':
                        occ.update(status='cancelled', reason='已转为单次事项', version=occ['version'] + 1)
        if old_rule and task['recurrence']:
            effective_on = (monday(now.date()) + timedelta(days=7)).isoformat()
            history = task.setdefault('definition_history', [{'effective_on': monday(parse_date(previous['starts_on'])).isoformat(),
                                                              'definition': definition_snapshot(previous)}])
            history.append({'effective_on': effective_on, 'definition': definition_snapshot(task)})
            for member in previous['assignee_ids']:
                if member not in task['assignee_ids']:
                    task.setdefault('former_assignees_until', {})[member] = effective_on
        for occ in doc['occurrences'].values():
            if occ['task_id'] != task['id'] or occ['status'] != 'open':
                continue
            # Existing weekly snapshots are immutable; new definition applies next week.
            if occ['period_key'] != 'once' and occ['period_start'] <= now.date().isoformat():
                continue
            fresh = occurrence(task, parse_date(occ['period_start']) if occ['period_start'] else None)
            fresh['version'] = occ['version'] + 1
            fresh['member_progress'] = {m: occ['member_progress'].get(m, p) for m, p in fresh['member_progress'].items()}
            occ.update(fresh)
