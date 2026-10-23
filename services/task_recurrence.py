"""Date-only weekly instances, materialized on demand without a scheduler."""
from copy import deepcopy
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from services.task_store import TaskError

WEEKDAYS = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU']


def parse_date(value):
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError()
        return parsed
    except (TypeError, ValueError) as exc:
        raise TaskError('invalid_date', '日期格式必须为 YYYY-MM-DD。') from exc


def monday(day):
    return day - timedelta(days=day.weekday())


def validate_rule(rule):
    if rule is None:
        return
    if (not isinstance(rule, dict) or rule.get('frequency') != 'weekly'
            or rule.get('interval', 1) != 1 or rule.get('weekday') not in [None, *WEEKDAYS]
            or rule.get('week_start', 'MO') != 'MO'
            or set(rule) - {'frequency', 'interval', 'week_start', 'weekday'}):
        raise TaskError('unsupported_recurrence', '首版仅支持每周一次，请补充每周规则。')


def definition_snapshot(task):
    return {k: deepcopy(task.get(k)) for k in ('title', 'recurrence', 'due_date', 'due_at', 'timezone',
            'assignee_ids', 'completion_mode', 'rule_revision')}


def occurrence(task, period=None):
    if period and task.get('definition_history'):
        effective = [entry for entry in task['definition_history'] if entry['effective_on'] <= period.isoformat()]
        if effective:
            definition = max(enumerate(effective), key=lambda pair: (pair[1]['effective_on'], pair[0]))[1]['definition']
            task = {**task, **deepcopy(definition)}
    rule = task['recurrence']
    due = task.get('due_date')
    if rule:
        due = (period + timedelta(days=WEEKDAYS.index(rule['weekday']) if rule.get('weekday') else 6)).isoformat()
    due_at = task.get('due_at')
    if rule and due_at:
        original = datetime.fromisoformat(due_at).astimezone(ZoneInfo(task['timezone']))
        due_at = datetime.combine(parse_date(due), original.timetz()).isoformat()
    key = period.isoformat() if period else 'once'
    return {'id': task['id'] + ':' + key, 'task_id': task['id'], 'period_key': key,
            'period_start': period.isoformat() if period else None,
            'period_end': (period + timedelta(days=7)).isoformat() if period else None,
            'due_date': due, 'due_at': due_at, 'status': 'open',
            'assignee_ids': list(task['assignee_ids']), 'title_snapshot': task['title'],
            'rule_revision': task.get('rule_revision', 1), 'completion_mode': task['completion_mode'],
            'member_progress': {mid: {'status': 'open', 'completed_by': None, 'completed_at': None} for mid in task['assignee_ids']},
            'completed_by': None, 'completed_at': None, 'version': 1}


def materialize(doc, task, today, limit=52):
    if not task['actionable'] or task['lifecycle'] != 'active':
        return True
    if not task['recurrence']:
        row = occurrence(task)
        doc['occurrences'].setdefault(row['id'], row)
        return True
    start = parse_date(task['starts_on'])
    if start > today:
        return True
    current = monday(today)
    # Current period is always available even when historical catch-up is bounded.
    def add(period):
        row = occurrence(task, period)
        if row['due_date'] < task['starts_on']:
            return
        doc['occurrences'].setdefault(row['id'], row)
    if not any(a <= current.isoformat() < b for a, b in task.get('paused_periods', [])):
        add(current)
    cursor = parse_date(task.get('cursor') or monday(start).isoformat())
    count = 0
    excluded = task.get('paused_periods', [])
    while cursor <= current and count < limit:
        if not any(a <= cursor.isoformat() < b for a, b in excluded):
            add(cursor)
        cursor += timedelta(days=7)
        count += 1
    task['cursor'] = cursor.isoformat()
    return cursor > current


def project(task, start, end):
    if not task['recurrence'] or task['lifecycle'] != 'active':
        return []
    period = monday(start)
    result = []
    for _ in range(53):
        if period > end:
            break
        row = occurrence(task, period)
        if row['due_date'] >= task['starts_on'] and start.isoformat() <= row['due_date'] <= end.isoformat():
            result.append({**deepcopy(row), 'projected': True})
        period += timedelta(days=7)
    return result
