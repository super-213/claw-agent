"""Object permissions are independent of technical administrator privileges."""
from services.task_store import TaskError


def currently_assigned(task, member_id, today=None):
    if today is None:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo(task['timezone'])).date()
    return member_id in task['assignee_ids'] or today.isoformat() < task.get('former_assignees_until', {}).get(member_id, '')


def can_read(task, member_id, today=None):
    return (task['visibility'] == 'household' or member_id == task['created_by']
            or currently_assigned(task, member_id, today) or member_id in task.get('related_member_ids', []))


def visible_task(doc, task_id, member_id, today=None):
    task = doc['tasks'].get(task_id)
    if not task or not can_read(task, member_id, today):
        raise TaskError('task_not_found', status=404)
    return task


def require_creator(task, member_id):
    if task['created_by'] != member_id:
        raise TaskError('forbidden', '仅交代者可以修改整个事项。', status=403)


def check_version(obj, expected):
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise TaskError('expected_version_required')
    if obj['version'] != expected:
        raise TaskError('version_conflict', '事项已被更新，请刷新后重试。', status=409, current_version=obj['version'])
