"""Legacy HTTP routes project the same ledger and never write old reminder files."""
from services.task_store import TaskError


class TaskLegacyAdapter:
    def __init__(self, service):
        self.service = service

    def resolve(self, legacy_id, kind='reminder'):
        return self.service.store.snapshot()['legacy_map'].get(kind + ':' + legacy_id, legacy_id)

    def list(self, user, kind='reminder', **filters):
        params = {'view': 'visible'}
        if filters.get('status'):
            params['status'] = {'scheduled': 'open', 'sent': 'open', 'failed': 'open', 'snoozed': 'open'}.get(filters['status'], filters['status'])
        if kind == 'schedule':
            params['recurring'] = True
        if filters.get('next_run_before'):
            params['due_to'] = filters['next_run_before'][:10]
        if filters.get('recipient_user_id'):
            member = next((m for m in self.service.members.list() if m['user_id'] == filters['recipient_user_id']), None)
            if not member:
                return {'reminders': [], 'schedules': []}
            params['assignee_id'] = member['member_id']
        result = self.service.list(user, **params)
        rows = [self.project(r['task'], r['occurrence']) for r in result['items']]
        return {**result, 'reminders' if kind == 'reminder' else 'schedules': rows,
                'compatibility': '事项仅通过查询和工作台查看，不主动通知。'}

    def project(self, task, occ):
        return {**task, 'status': (occ or {}).get('status', 'information'),
                'next_run_at': (occ or {}).get('due_at') or (occ or {}).get('due_date'),
                'occurrence': occ, 'channels': [], 'recipients': task['assignee_ids'],
                'trigger': {'run_at': (occ or {}).get('due_at'), 'rrule': task['recurrence']}}

    def get(self, user, legacy_id, kind='reminder'):
        result = self.service.get(user, self.resolve(legacy_id, kind))
        return {**result, 'reminder': self.project(result['task'], next(iter(result['occurrences']), None))}

    def create(self, user, payload):
        if not payload.get('invocation') or not payload.get('items'):
            raise TaskError('task_api_required', '请使用事项接口显式选择空间、日程/备忘和成员；旧发送参数不再生效。', status=409)
        return self.service.create(user, payload['items'], payload['invocation'], request_id=payload.get('request_id'))

    def change(self, user, legacy_id, action, payload, kind='reminder'):
        task_id = self.resolve(legacy_id, kind)
        if action == 'snooze':
            raise TaskError('task_api_required', '事项不主动发送，请在事项详情中修改执行日期。', status=409)
        if payload.get('expected_version') is None or not payload.get('request_id'):
            raise TaskError('task_api_required', '修改需提交 request_id、expected_version；完成需 occurrence_id。', status=409)
        occurrence_id = payload.get('occurrence_id')
        if action in {'complete', 'cancel'} and not occurrence_id:
            raise TaskError('occurrence_id_required')
        return self.service.change(user, task_id, action, expected_version=payload['expected_version'],
                                   request_id=payload['request_id'], occurrence_id=occurrence_id, patch=payload.get('patch', {}))
