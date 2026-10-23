"""Auditable legacy import; dry runs never modify sources or the ledger."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import uuid
from zoneinfo import ZoneInfo
from services.task_recurrence import materialize, occurrence, monday, WEEKDAYS
from services.task_store import TaskError, TaskStore


def weekly_rule(value):
    parts = dict(part.split('=', 1) for part in str(value).split(';') if '=' in part)
    if not parts or parts.get('FREQ') != 'WEEKLY' or set(parts) - {'FREQ', 'INTERVAL', 'BYDAY', 'BYHOUR', 'BYMINUTE', 'WKST'}:
        return None
    if parts.get('INTERVAL', '1') != '1' or parts.get('WKST', 'MO') != 'MO' or parts.get('BYDAY') not in [None, *WEEKDAYS]:
        return None
    for field, upper in [('BYHOUR', 23), ('BYMINUTE', 59)]:
        if field in parts and (not parts[field].isdigit() or not 0 <= int(parts[field]) <= upper):
            return None
    return {'frequency': 'weekly', 'interval': 1, 'week_start': 'MO', 'weekday': parts.get('BYDAY')}


class TaskMigration:
    def __init__(self, service):
        self.service = service
        self.root = service.members.home.root_dir

    def plan(self):
        service = self.service
        now = service.now()
        members = {m['user_id']: m['member_id'] for m in service.members.list()}
        doc = json.loads(service.store.path.read_text()) if service.store.path.exists() else TaskStore.empty()
        report = {'created': [], 'review': [], 'already_migrated': [], 'source_count': 0}
        tasks = {}
        reviews = {}
        for kind, filename, collection in [('reminder', 'reminders.json', 'reminders'), ('schedule', 'schedules.json', 'schedules')]:
            path = self.root / filename
            rows = json.loads(path.read_text(encoding='utf-8')).get(collection, []) if path.exists() else []
            seen = set()
            for row in rows:
                report['source_count'] += 1
                source_id = row.get('id')
                if not source_id or source_id in seen:
                    raise TaskError('duplicate_or_missing_legacy_id')
                seen.add(source_id)
                key = kind + ':' + source_id
                if key in doc['legacy_map']:
                    report['already_migrated'].append(key)
                    continue
                trigger = row.get('trigger') or {}
                rule_text = trigger.get('rrule') or row.get('rrule')
                rule = weekly_rule(rule_text) if rule_text else None
                recipients = row.get('recipients') or [row.get('created_by')]
                creator = members.get(row.get('created_by'))
                reasons = []
                if not creator or any(r not in members for r in recipients):
                    reasons.append('unbound_member')
                if rule_text and not rule:
                    reasons.append('unsupported_recurrence')
                if rule_text and row.get('status') == 'completed':
                    reasons.append('completed_series_semantics_unknown')
                if len(recipients) > 1:
                    reasons.append('multi_recipient_completion_mode_unknown')
                stamp = trigger.get('run_at') or row.get('next_run_at')
                due_date = None
                due_at = None
                if stamp:
                    try:
                        parsed = datetime.fromisoformat(stamp)
                        if not parsed.tzinfo:
                            raise ValueError()
                        due_date = parsed.astimezone(service.zone).date().isoformat()
                        due_at = parsed.isoformat()
                    except (TypeError, ValueError):
                        reasons.append('invalid_legacy_time')
                if rule_text and rule:
                    parts = dict(p.split('=', 1) for p in rule_text.split(';') if '=' in p)
                    if 'BYHOUR' in parts or 'BYMINUTE' in parts:
                        base = now.replace(hour=int(parts.get('BYHOUR', 0)), minute=int(parts.get('BYMINUTE', 0)), second=0, microsecond=0)
                        due_at = base.isoformat()
                        due_date = base.date().isoformat()
                if not stamp and not rule:
                    reasons.append('missing_date')
                if reasons:
                    reviews[key] = {'legacy_type': kind, 'legacy_id': source_id, 'reasons': reasons,
                                    'source': deepcopy(row), 'status': 'needs_review'}
                    report['review'].append({'source': key, 'reasons': reasons})
                if not creator or 'unbound_member' in reasons:
                    continue
                assignees = list(dict.fromkeys(members[r] for r in recipients))
                task_id = 'task_legacy_' + hashlib.sha256(key.encode()).hexdigest()[:24]
                household = service.members.home.household().get('id', 'household_default')
                task = {'id': task_id, 'household_id': household, 'space_type': 'personal',
                        'space_id': 'personal:' + creator, 'space_owner_id': creator, 'visibility': 'participants',
                        'temporal_type': 'timed', 'actionable': True, 'title': row.get('title') or '旧事项',
                        'description': row.get('description', ''), 'category': None, 'created_by': creator,
                        'assignee_ids': assignees, 'related_member_ids': [], 'completion_mode': 'all',
                        'lifecycle': 'archived' if reasons or (rule and row.get('status') == 'cancelled') else 'paused' if row.get('status') == 'paused' else 'active',
                        'timezone': service.timezone_name, 'recurrence': rule,
                        # Migration knows only the current period, never invent older completions.
                        'starts_on': now.date().isoformat() if rule else None,
                        'due_date': due_date, 'due_at': due_at, 'version': 1, 'rule_revision': 1,
                        'created_at': row.get('created_at') or now.isoformat(), 'updated_at': now.isoformat(),
                        'source': {'legacy_type': kind, 'legacy_id': source_id, 'legacy_status': row.get('status')},
                        'migration_review': reasons, 'history_before_migration': 'unknown'}
                tasks[key] = task
                report['created'].append({'source': key, 'task_id': task_id, 'lifecycle': task['lifecycle']})
        report['checks'] = {'accounted_for': report['source_count'] == len(report['already_migrated']) + len(set(tasks) | set(reviews)),
                            'no_delivery': True}
        return report, tasks, reviews

    def execute(self):
        # Run with legacy writers disabled; new API writes are protected by the ledger transaction lock.
        report, tasks, reviews = self.plan()
        if not report['checks']['accounted_for']:
            raise TaskError('migration_validation_failed')
        backup = self.root / 'backups' / ('task-migration-' + uuid.uuid4().hex)
        backup.mkdir(parents=True, mode=0o700)
        for path in self.root.iterdir():
            if path.is_file() and path.name != 'tasks.json.lock':
                shutil.copy2(path, backup / path.name)
        with self.service.store.transaction() as doc:
            baseline = deepcopy(doc)
            TaskStore.write_atomic(backup / 'ledger-before.json', baseline)
            for key, task in tasks.items():
                if key in doc['legacy_map']:
                    continue
                doc['tasks'][task['id']] = task
                doc['legacy_map'][key] = task['id']
                if task['lifecycle'] == 'active':
                    materialize(doc, task, self.service.now().date())
                elif task['lifecycle'] == 'paused':
                    task['paused_on'] = self.service.now().date().isoformat()
                if not task['recurrence'] and task.get('due_date'):
                    row = occurrence(task)
                    legacy_status = task['source']['legacy_status']
                    if legacy_status == 'completed':
                        row.update(status='completed', completed_by=None, completed_at=None)
                        row['legacy_completion_unknown_actor'] = True
                    elif legacy_status == 'cancelled':
                        row['status'] = 'cancelled'
                    doc['occurrences'][row['id']] = row
            doc['migration_review'].update(reviews)
            doc['migration'] = {'backup': str(backup), 'at': self.service.now().isoformat(),
                                'cutover_revision': doc['revision'] + 1}
        report['backup'] = str(backup)
        TaskStore.write_atomic(backup / 'report.json', report)
        return report

    def rollback(self, backup, *, writes_paused=False, apply=False):
        if apply and not writes_paused:
            raise TaskError('pause_writes_before_rollback')
        backup = Path(backup).resolve()
        if self.root.resolve() / 'backups' not in backup.parents:
            raise TaskError('invalid_backup_path')
        baseline = json.loads((backup / 'ledger-before.json').read_text())
        with self.service.store.transaction() as current:
            changed = [key for key, value in current['tasks'].items() if baseline['tasks'].get(key) != value]
            report = {'changed_task_ids': changed, 'current_revision': current['revision'], 'apply': apply,
                      'warning': '恢复前必须保存并人工合并导出的切换后变更。'}
            if apply:
                exported = backup / ('post-cutover-' + uuid.uuid4().hex + '.json')
                TaskStore.write_atomic(exported, current)
                report['export'] = str(exported)
                # Atomic rollback preserves an export of ALL post-cutover data and operations.
                revision = current['revision']
                current.clear()
                current.update(deepcopy(baseline))
                current['revision'] = revision
                current['rollback_export'] = str(exported)
            return report
