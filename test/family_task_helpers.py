from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import multiprocessing
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest

from services.family_member_service import FamilyMemberService
from services.family_task_service import FamilyTaskService
from services.home_service import HomeDataService
from services.task_commands import normalize_invocation
from services.task_migration import TaskMigration
from services.task_recurrence import monday
from services.task_store import TaskError, TaskStore
from services.user_store import UserStore


@pytest.fixture
def family(tmp_path):
    home = HomeDataService(tmp_path / 'home')
    users = UserStore(tmp_path / 'users.json')
    people = [users.create_user(username=name, password='secret123', role='admin' if name == 'alice' else 'user') for name in ('alice', 'bob', 'carol')]
    members = FamilyMemberService(home, users)
    for person, label in zip(people, ('A', 'B', 'C')):
        members.update(label, {'user_id': person['id'], 'display_name': label, 'aliases': ['同名']}, people[0])
    clock = [datetime(2026, 10, 23, 12, tzinfo=ZoneInfo('Asia/Shanghai'))]
    service = FamilyTaskService(TaskStore(home.root_dir / 'tasks.json'), members, clock=lambda: clock[0])
    return service, people, clock


def invocation(space='personal', temporal='undated', ids=(), **extra):
    return {'command': ('家庭' if space == 'household' else '') + ('日程' if temporal == 'timed' else '备忘'),
            'space_type': space, 'temporal_type': temporal, 'mentions': [{'member_id': m} for m in ids],
            'actionable': True, 'completion_mode': 'all', **extra}


def create(family, *, items=None, inv=None, actor=0, rid='create'):
    service, users, _ = family
    result = service.create(users[actor], items or [{'title': '买牛奶'}], inv or invocation(), request_id=rid)
    task = result['tasks'][0]
    return task, service.get(users[actor], task['id'])['occurrences']


def change(family, task, action, *, actor=0, occ=None, rid=None, patch=None, version=None):
    service, users, _ = family
    return service.change(users[actor], task['id'], action, expected_version=version or (occ or task)['version'],
                          request_id=rid or action, occurrence_id=occ['id'] if occ else None, patch=patch)


