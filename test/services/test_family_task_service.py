from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import multiprocessing
from pathlib import Path
import pytest
from services.family_task_service import FamilyTaskService
from services.task_commands import normalize_invocation
from services.task_migration import TaskMigration
from services.task_recurrence import monday
from services.task_store import TaskError, TaskStore
from family_task_helpers import invocation, create, change


def test_batch_persistence_and_idempotency(family):
    service, users, _ = family
    items = [{'title': title} for title in ('买牛奶', '交电费', '预约体检')]
    result = service.create(users[0], items, invocation(), request_id='request')
    assert len(service.list(users[0])['items']) == 3
    restarted = FamilyTaskService(TaskStore(service.store.path), service.members)
    assert len(restarted.list(users[0])['items']) == 3
    assert result == service.create(users[0], items, invocation(), request_id='request')
    with pytest.raises(TaskError, match='idempotency_conflict'):
        service.create(users[0], [{'title': '另一条'}], invocation(), request_id='request')
    with pytest.raises(TaskError):
        service.create(users[0], [{'title': '有效'}, {'title': ''}], invocation(), request_id='bad')
    assert len(service.list(users[0])['items']) == 3


def test_space_permissions_admin_is_not_a_task_superuser(family):
    service, users, _ = family
    task, _ = create(family, actor=1, inv=invocation(ids=['C']))
    for index in (1, 2):
        assert service.get(users[index], task['id'])['task']['id'] == task['id']
    assert service.list(users[0], view='visible')['total'] == 0
    assert service.summary(users[0], view='visible')['counts']['open'] == 0
    with pytest.raises(TaskError, match='task_not_found'):
        service.get(users[0], task['id'])
    with pytest.raises(TaskError, match='forbidden'):
        change(family, task, 'update', actor=2, patch={'title': '改名'})
    with pytest.raises(TaskError, match='member_unavailable'):
        create(family, inv=invocation(ids=['unknown']), rid='unknown')


@pytest.mark.parametrize('mode', ['all', 'any'])
def test_multiple_assignees_progress_and_reopen(family, mode):
    service, users, _ = family
    task, rows = create(family, inv=invocation('household', temporal='timed', ids=['A', 'B'], completion_mode=mode),
                        items=[{'title': '协作事项', 'due_date': '2026-10-23'}])
    done = change(family, task, 'complete', occ=rows[0])['occurrence']
    assert done['status'] == ('completed' if mode == 'any' else 'open')
    assert done['member_progress']['B']['status'] == 'open'
    with pytest.raises(TaskError, match='version_conflict'):
        change(family, task, 'complete', actor=1, occ=rows[0], rid='stale')
    if mode == 'any':
        # Once an any-person item is completed, others cannot rewrite that result.
        with pytest.raises(TaskError, match='task_read_only'):
            change(family, task, 'complete', actor=1, occ=done, rid='b-done')
        restored = change(family, task, 'reopen', occ=done)['occurrence']
        assert restored['status'] == 'open' and restored['member_progress']['B']['status'] == 'open'
        return
    done2 = change(family, task, 'complete', actor=1, occ=done, rid='b-done')['occurrence']
    assert done2['status'] == 'completed'
    assert done2['member_progress']['A']['status'] == 'completed'
    restored = change(family, task, 'reopen', occ=done2)['occurrence']
    assert restored['member_progress']['B']['status'] == 'completed'
    assert len(service.list(users[2], view='household', status='')['items']) == 1


def test_information_and_explicit_input_validation(family):
    service, users, _ = family
    task, rows = create(family, items=[{'title': '钥匙在抽屉'}], inv=invocation(actionable=False, ids=['B']))
    assert not rows and task['related_member_ids'] == ['B']
    assert service.summary(users[1])['counts']['information'] == 1
    assert service.summary(users[1])['counts']['open'] == 0
    with pytest.raises(TaskError, match='schedule_date_required'):
        create(family, inv=invocation(temporal='timed'), rid='missing-date')
    with pytest.raises(TaskError, match='undated_has_date'):
        create(family, items=[{'title': '日期', 'due_date': '2026-10-24'}], rid='memo-date')
    with pytest.raises(TaskError, match='memo_time_choice_required'):
        create(family, items=[{'title': '明天买奶'}], rid='text-date')
    create(family, items=[{'title': '明天买奶'}], inv=invocation(literal_time_text=True), rid='literal')
    with pytest.raises(TaskError, match='invocation_conflict'):
        create(family, items=[{'title': '改空间', 'space_type': 'household'}], rid='override')
    with pytest.raises(TaskError, match='explicit_selection_required'):
        service.create(users[0], [{'title': '未选空间'}], None, request_id='draft')
    with pytest.raises(TaskError, match='unsupported_recurrence'):
        create(family, items=[{'title': '每天', 'recurrence': {'frequency': 'daily'}}], inv=invocation(temporal='timed'), rid='daily')


def test_two_simultaneous_claims(family):
    service, users, _ = family
    task, _ = create(family, inv=invocation('household'))
    def claim(index):
        try:
            return change(family, task, 'claim', actor=index, rid='claim-' + str(index))['task']['assignee_ids']
        except TaskError as error:
            return error.code
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(claim, [1, 2]))
    assert results.count('version_conflict') == 1
    assert len(service.get(users[0], task['id'])['task']['assignee_ids']) == 1


def test_members_alias_and_disabled_account(family):
    service, users, _ = family
    assert len(service.members.resolve('同名', users[0])) == 3
    service.members.update('A', {'speaker_aliases': {'爸爸': 'B'}}, users[0])
    service.members.update('B', {'speaker_aliases': {'爸爸': 'C'}}, users[0])
    assert service.members.resolve('爸爸', users[0])[0]['member_id'] == 'B'
    assert service.members.resolve('爸爸', users[1])[0]['member_id'] == 'C'
    task, _ = create(family, inv=invocation(ids=['B']))
    service.members.users.update_user(users[1]['id'], status='disabled')
    assert service.list(users[0], view='delegated')['items'][0]['assignee_unavailable'] == ['B']
    with pytest.raises(TaskError, match='member_unavailable'):
        create(family, inv=invocation(ids=['B']), rid='disabled')


def test_weekly_completion_cross_year_and_history(family):
    service, users, clock = family
    clock[0] = datetime(2026, 12, 27, 23, 59, tzinfo=service.zone)
    task, rows = create(family, items=[{'title': '买牛奶', 'recurrence': {'frequency': 'weekly', 'weekday': None}}], inv=invocation(temporal='timed'))
    assert rows[0]['period_key'] == '2026-12-21'
    assert rows[0]['due_date'] == '2026-12-27'
    change(family, task, 'complete', occ=rows[0])
    clock[0] = datetime(2026, 12, 28, 0, 1, tzinfo=service.zone)
    items = service.list(users[0], current_only=True)['items']
    assert len(items) == 1 and items[0]['occurrence']['status'] == 'open'
    history = service.get(users[0], task['id'])['occurrences']
    assert len(history) == 2
    assert next(o for o in history if o['period_key'] == '2026-12-21')['status'] == 'completed'


def test_future_projection_pause_resume_stop(family):
    service, users, clock = family
    task, rows = create(family, items=[{'title': '家务', 'starts_on': '2026-10-26', 'recurrence': {'frequency': 'weekly', 'weekday': 'WE'}}], inv=invocation(temporal='timed'))
    assert not rows
    projected = service.list(users[0], due_to='2026-11-01')['items']
    assert len(projected) == 1 and projected[0]['occurrence']['projected']
    assert not service.get(users[0], task['id'])['occurrences']
    clock[0] = datetime(2026, 10, 28, 12, tzinfo=service.zone)
    assert service.list(users[0])['items'][0]['occurrence']['due_date'] == '2026-10-28'
    paused = change(family, task, 'pause')['task']
    clock[0] = datetime(2026, 12, 2, 12, tzinfo=service.zone)
    assert len(service.get(users[0], task['id'])['occurrences']) == 1
    resumed = change(family, paused, 'resume')['task']
    assert len(service.get(users[0], task['id'])['occurrences']) == 2
    archived = change(family, resumed, 'archive')['task']
    assert archived['lifecycle'] == 'archived'
    history = service.get(users[0], task['id'])['occurrences']
    assert all(o['status'] == 'cancelled' for o in history if o['due_date'] >= clock[0].date().isoformat())
    assert next(o for o in history if o['due_date'] == '2026-10-28')['status'] == 'open'


def test_completed_memo_cannot_be_reactivated_by_converting_to_weekly(family):
    service, users, _ = family
    task, rows = create(family)
    done = change(family, task, 'complete', occ=rows[0])['occurrence']
    with pytest.raises(TaskError, match='task_read_only'):
        change(family, task, 'update', patch={'temporal_type': 'timed', 'recurrence': {'frequency': 'weekly', 'weekday': None}})
    occurrences = service.get(users[0], task['id'])['occurrences']
    assert len(occurrences) == 1 and occurrences[0]['status'] == done['status']
    assert occurrences[0]['member_progress'] == done['member_progress']


def test_bounded_catchup_current_first_and_query_idempotence(family):
    service, users, clock = family
    task, _ = create(family, items=[{'title': '很早开始', 'starts_on': '2020-01-01', 'recurrence': {'frequency': 'weekly', 'weekday': None}}], inv=invocation(temporal='timed'))
    result = service.list(users[0], current_only=True)
    assert not result['history_complete'] and result['total'] is None
    assert result['items'][0]['occurrence']['period_key'] == monday(clock[0].date()).isoformat()
    for _ in range(8):
        result = service.list(users[0])
    assert result['history_complete']
    before = service.store.snapshot()['revision']
    service.list(users[0])
    assert service.store.snapshot()['revision'] == before


def test_rename_and_move_space_audience(family):
    service, users, _ = family
    task, _ = create(family)
    with pytest.raises(TaskError, match='audience_confirmation_required'):
        change(family, task, 'update', patch={'space_type': 'household'})
    changed = change(family, task, 'update', patch={'space_type': 'household', 'audience_confirmed': True, 'title': '新标题'})['task']
    assert changed['id'] == task['id']
    assert service.get(users[2], task['id'])['task']['title'] == '新标题'


def test_literal_prefix_grammar():
    for value in ('/日程 明天', '/', '@', '@小明', 'https://example.org/ 日程', '`/ 日程`'):
        assert normalize_invocation(value) is None
    raw = '/ 家庭日程 @ A @ B 每周六大扫除'
    inv = invocation('household', 'timed')
    inv['mentions'] = [{'member_id': 'A', 'label': 'A', 'start': 7, 'end': 10},
                       {'member_id': 'B', 'label': 'B', 'start': 11, 'end': 14}]
    assert normalize_invocation(raw, inv)['body'] == '每周六大扫除'
    with pytest.raises(TaskError, match='unresolved_mentions'):
        normalize_invocation(raw)
    assert normalize_invocation('/ 备忘 联系 a@b.com 或 https://x/@ foo')['mentions'] == []


def _increment(path, count):
    store = TaskStore(path)
    for _ in range(count):
        with store.transaction() as doc:
            doc['counter'] = doc.get('counter', 0) + 1


def test_cross_process_lock_and_corrupt_file(tmp_path):
    path = tmp_path / 'tasks.json'
    context = multiprocessing.get_context('spawn')
    processes = [context.Process(target=_increment, args=(path, 12)) for _ in range(3)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(20)
        assert process.exitcode == 0
    assert TaskStore(path).snapshot()['counter'] == 36
    path.write_text('{broken')
    with pytest.raises(TaskError, match='ledger_corrupt'):
        TaskStore(path).snapshot()
    assert path.read_text() == '{broken'


def test_migration_preview_repeat_review_and_rollback(family):
    service, users, _ = family
    path = service.members.home.root_dir / 'reminders.json'
    rows = []
    for index, status in enumerate(('completed', 'cancelled', 'sent', 'failed', 'snoozed', 'scheduled')):
        rows.append({'id': str(index), 'title': status, 'created_by': users[0]['id'], 'recipients': [users[0]['id']], 'status': status,
                     'trigger': {'run_at': '2026-10-24T08:00:00+08:00'}})
    rows.extend([
        {'id': 'daily', 'title': '每日', 'created_by': users[0]['id'], 'trigger': {'rrule': 'FREQ=DAILY'}},
        {'id': 'unknown', 'title': '无人', 'created_by': 'missing', 'trigger': {}},
        {'id': 'weekly', 'title': '每周', 'created_by': users[0]['id'], 'trigger': {'rrule': 'FREQ=WEEKLY;BYDAY=WE'}},
        {'id': 'multi', 'title': '多人', 'created_by': users[0]['id'], 'recipients': [u['id'] for u in users[:2]], 'trigger': {'run_at': '2026-10-24T08:00:00+08:00'}},
    ])
    path.write_text(json.dumps({'reminders': rows}))
    migration = TaskMigration(service)
    before = path.read_bytes()
    report, _, _ = migration.plan()
    assert report['checks']['accounted_for'] and len(report['review']) == 3
    assert path.read_bytes() == before and not service.store.path.exists()
    report = migration.execute()
    assert len(service.store.snapshot()['legacy_map']) == 9
    assert service.store.snapshot()['migration_review']['reminder:unknown']['reasons'] == ['unbound_member', 'missing_date']
    assert path.read_bytes() == before
    repeat = migration.execute()
    assert len(repeat['created']) == 0
    assert len(service.store.snapshot()['tasks']) == 9
    states = {r['task']['title']: r['occurrence']['status'] for r in service.list(users[0], view='visible', status='')['items']}
    assert states['completed'] == 'completed' and states['sent'] == 'open' and states['cancelled'] == 'cancelled'
    create(family, rid='new-after-migration')
    preview = migration.rollback(report['backup'])
    assert preview['changed_task_ids']
    with pytest.raises(TaskError, match='pause_writes'):
        migration.rollback(report['backup'], apply=True)
    rolled = migration.rollback(report['backup'], apply=True, writes_paused=True)
    assert Path(rolled['export']).exists()
    assert not service.store.snapshot()['tasks']


def test_weekly_future_edit_and_leave_preserve_current_and_old_snapshots(family):
    service, users, clock = family
    task, rows = create(family, items=[{'title': '旧内容', 'recurrence': {'frequency': 'weekly', 'weekday': None}}],
                        inv=invocation(temporal='timed', ids=['B']))
    updated = change(family, task, 'update', patch={'title': '未来内容', 'recurrence': {'frequency': 'weekly', 'weekday': 'WE'}})['task']
    current = service.get(users[1], task['id'])['occurrences'][0]
    assert current['title_snapshot'] == '旧内容' and current['due_date'] == '2026-10-25'
    left = change(family, updated, 'leave', actor=1, patch={'reason': '下周无暇参与'})['task']
    assert not left['assignee_ids']
    assert service.list(users[1])['items'][0]['occurrence']['assignee_ids'] == ['B']
    clock[0] = datetime(2026, 10, 28, 12, tzinfo=service.zone)
    assert not service.list(users[1], view='visible')['items']
    with pytest.raises(TaskError, match='task_not_found'):
        service.get(users[1], task['id'])
    rows = service.get(users[0], task['id'])['occurrences']
    next_period = next(o for o in rows if o['period_key'] == '2026-10-26')
    assert next_period['title_snapshot'] == '未来内容' and next_period['due_date'] == '2026-10-28'
    assert not next_period['assignee_ids'] and next_period['status'] == 'open'


def test_weekly_explicit_time_advances_with_local_date(family):
    service, users, clock = family
    task, rows = create(family, items=[{'title': '倒垃圾', 'due_date': '2026-10-23',
        'due_at': '2026-10-23T08:00:00+08:00', 'recurrence': {'frequency': 'weekly', 'weekday': 'SU'}}], inv=invocation(temporal='timed'))
    assert rows[0]['due_at'] == '2026-10-25T08:00:00+08:00'
    clock[0] = datetime(2026, 10, 26, 12, tzinfo=service.zone)
    current = service.list(users[0], current_only=True)['items'][0]['occurrence']
    assert current['due_at'] == '2026-11-01T08:00:00+08:00'
    preview = service.get(users[0], task['id'])['preview']
    assert preview[0]['period_key'] == '2026-11-02'


def test_corrupt_household_preview_never_moves_or_replaces_source(family):
    service, _, _ = family
    path = service.members.home.root_dir / 'household.json'
    path.write_text('{bad')
    with pytest.raises(TaskError, match='household_corrupt'):
        TaskMigration(service).plan()
    assert path.read_text() == '{bad'


def test_inline_mentions_spaces_and_quoted_text():
    raw = '/ 日程 明天 @ Alice A 买牛奶'
    start = raw.index('@ ')
    selected = invocation(temporal='timed')
    selected['mentions'] = [{'member_id': 'A', 'label': 'Alice A', 'start': start, 'end': start + len('@ Alice A')}]
    parsed = normalize_invocation(raw, selected)
    assert parsed['body'] == '明天  买牛奶'
    assert parsed['mentions'][0]['member_id'] == 'A'
    assert not normalize_invocation('/ 备忘 引用“文字 @ 小明” 或 `@ 小红`')['mentions']


def test_completed_history_cannot_be_rewritten_by_occurrence_edit(family):
    task, rows = create(family)
    completed = change(family, task, 'complete', occ=rows[0])['occurrence']
    for action in ('update_occurrence', 'skip', 'cancel'):
        with pytest.raises(TaskError, match='task_read_only'):
            change(family, task, action, occ=completed, patch={'title': '更改过去'}, rid=action)
