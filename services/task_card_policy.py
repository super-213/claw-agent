"""Server-clock lifecycle policy shared by cards, legacy APIs and native tools."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from services.task_recurrence import parse_date
from services.task_store import TaskError


def temporal_state(task, occ, now):
    zone = ZoneInfo(task['timezone'])
    now = now.astimezone(zone)
    due = (occ or {}).get('due_date') or (task.get('due_date') if not task.get('recurrence') else None)
    until = datetime.combine(parse_date(due) + timedelta(days=1), time.min, zone) if due else None
    state = 'expired' if until and now >= until else 'in_progress' if due == now.date().isoformat() else 'upcoming' if due else 'undated'
    next_day = datetime.combine(now.date() + timedelta(days=1), time.min, zone)
    return {'server_now': now.isoformat(), 'time_state': state,
            'valid_until': until.isoformat() if until else None,
            'next_transition_at': next_day.isoformat() if due and state != 'expired' else None}


def readonly_reason(task, occ, now, *, series=False):
    if not series and temporal_state(task, occ, now)['time_state'] == 'expired':
        return 'expired'
    if task['lifecycle'] == 'archived':
        return 'archived'
    status = (occ or {}).get('status')
    if status in {'cancelled', 'skipped', 'completed'}:
        return status
    if task['lifecycle'] == 'paused':
        return 'paused'
    return None


def assert_writable(task, occ, now, action='update', *, series=False):
    reason = readonly_reason(task, occ, now, series=series)
    if reason == 'expired':
        raise TaskError('task_card_expired', '该事项已过期，无法修改。', status=409,
                        read_only=True, read_only_reason=reason, **temporal_state(task, occ, now))
    # Same-day timed completion may only be reopened by its own assignee;
    # the action service checks that identity. Undated completed memos stay frozen.
    if reason == 'completed' and action == 'reopen' and task['temporal_type'] == 'timed':
        return
    if reason == 'paused' and action in {'resume', 'archive'}:
        return
    if reason:
        raise TaskError('task_read_only', '该事项已结束或暂停，当前操作不可用。', status=409,
                        read_only=True, read_only_reason=reason)
