from copy import deepcopy
from datetime import datetime, timedelta
import asyncio
import json

import pytest

from agent_runtime import ToolCall, ToolResult
from agent_runtime.card_presenter import CardPresenter
from agent_runtime.family_task_tools import register_family_task_tools
from agent_runtime.registry import ToolRegistry
from family_task_helpers import create, invocation, change
from services.task_store import TaskError
from test_family_task_api import api, FakeLLM  # noqa: F401
import web_app


def card(clients, task_id, instance_id=None, actor=0):
    response = clients[actor].get(f'/api/home/tasks/{task_id}/card', params={'instance_id': instance_id} if instance_id else {})
    assert response.status_code == 200, response.text
    return response.json()


def save(clients, view, **changes):
    payload = {'request_id': 'save-card', 'expected_task_version': view['task']['version'],
               'occurrence_id': view['resource'].get('instance_id'),
               'expected_occurrence_version': (view['occurrence'] or {}).get('version'), **changes}
    return clients[0].patch(f"/api/home/tasks/{view['task']['id']}/card", json=payload)


@pytest.mark.parametrize('space,temporal', [('personal', 'timed'), ('household', 'timed'), ('personal', 'undated'), ('household', 'undated')])
def test_native_creation_persists_cards_before_truncation(api, monkeypatch, space, temporal):
    clients, service, _, _ = api
    session = clients[0].post('/api/sessions').json()
    items = [{'title': f'卡片条目{i}', **({'due_date': '2026-10-24'} if temporal == 'timed' else {})} for i in range(8)]
    monkeypatch.setitem(web_app.config.config, 'tool_output_max_chars', 1000)
    monkeypatch.setattr(web_app, '_new_llm_client', lambda: FakeLLM([ToolCall('call', f'family_{temporal}_memo_create', {'items': items})]))
    text = ('给全家' if space == 'household' else '帮我') + ('创建日程，明天处理' if temporal == 'timed' else '创建备忘，待办事项')
    response = clients[0].post('/api/chat/stream', json={'session_id': session['id'], 'message': text})
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    blocks = [b for e in events if e['type'] == 'ui_blocks' for b in e['blocks']]
    assert len(blocks) == 8
    final = web_app.store.load_session(session['id'])['messages'][-1]
    assert {b['card_id'] for b in final['ui_blocks']} == {b['card_id'] for b in blocks}
    assert all(b['source']['tool_call_id'] == 'call' for b in blocks)
    assert all(b['resource']['type'] == 'family_task' for b in blocks)
    assert not any('title' in b for b in blocks)
    first = card(clients, blocks[0]['resource']['id'], blocks[0]['resource']['instance_id'])
    assert first['task']['space_type'] == space
    assert clients[1].get('/api/home/tasks/' + first['task']['id'] + '/card').status_code == (200 if space == 'household' else 404)
    assert len(service.store.snapshot()['tasks']) == 8


def test_atomic_save_all_fields_status_and_no_duplicate(api):
    clients, service, users, clock = api
    task, _ = create((service, users, clock), inv=invocation(temporal='timed'), items=[{'title': '出门', 'due_date': '2026-10-24'}])
    before = card(clients, task['id'])
    changes = dict(definition_patch={'title': '去上海', 'description': '带身份证', 'space_type': 'household',
        'due_date': '2026-10-25', 'due_at': '2026-10-25T15:00:00+08:00', 'assignee_ids': ['A', 'B'], 'completion_mode': 'any'},
        audience_confirmed=True, occurrence_action={'action': 'complete', 'expected_version': before['occurrence']['version']})
    response = save(clients, before, **changes)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['task']['id'] == task['id']
    assert result['occurrence']['status'] == 'completed'
    assert result['occurrence']['member_progress']['B']['status'] == 'open'
    assert result['task']['title'] == '去上海' and result['task']['space_type'] == 'household'
    assert result['task_changed']['task_ids'] == [task['id']]
    assert save(clients, before, **changes).status_code == 200
    assert len(service.store.snapshot()['tasks']) == 1
    assert len([e for e in service.store.snapshot()['events'] if e['action'] == 'card_save']) == 1
    assert result['changes']['before']['task']['title'] == '出门'


def test_failed_status_or_stale_version_rolls_back_entire_save(api):
    clients, service, users, clock = api
    task, _ = create((service, users, clock), inv=invocation(temporal='timed'), items=[{'title': '原始标题', 'due_date': '2026-10-24'}])
    original = card(clients, task['id'])
    doc = service.store.snapshot()
    response = save(clients, original, definition_patch={'title': '不能保存', 'assignee_ids': ['B']},
        occurrence_action={'action': 'complete', 'expected_version': original['occurrence']['version']})
    assert response.status_code == 403, response.text
    assert service.store.snapshot() == doc
    response = save(clients, original, definition_patch={'title': '另一个标题'},
        occurrence_action={'action': 'complete', 'expected_version': 999})
    assert response.status_code == 409 and response.json()['error'] == 'version_conflict'
    assert service.store.snapshot() == doc


def test_expiry_freezes_edits_but_allows_late_completion(api):
    clients, service, users, clock = api
    clock[0] = datetime(2026, 10, 27, 12, tzinfo=service.zone)
    task, _ = create((service, users, clock), inv=invocation(temporal='timed'), items=[{'title': '去上海', 'due_date': '2026-10-28', 'due_at': '2026-10-28T09:00:00+08:00'}])
    assert card(clients, task['id'])['time_state'] == 'upcoming'
    clock[0] = datetime(2026, 10, 28, 23, 59, 59, tzinfo=service.zone)
    before = card(clients, task['id'])
    assert before['time_state'] == 'in_progress' and not before['read_only']
    clock[0] += timedelta(seconds=1)
    expired = card(clients, task['id'])
    assert expired['time_state'] == 'expired' and not expired['read_only']
    assert expired['occurrence']['status'] == 'open'
    assert expired['capabilities'] == {'editable_fields': [], 'actions': ['complete']}
    frozen = service.store.snapshot()
    response = save(clients, before, definition_patch={'due_date': '2027-01-01', 'due_at': None, 'title': '试图改期'})
    assert response.status_code == 409 and response.json()['error'] == 'task_card_expired'
    legacy = clients[0].patch('/api/home/tasks/' + task['id'], json={'request_id': 'old-api', 'expected_version': before['task']['version'], 'patch': {'title': '绕过按钮'}})
    assert legacy.status_code == 409 and legacy.json()['error'] == 'task_card_expired'
    url = f"/api/home/tasks/{task['id']}/occurrences/{before['occurrence']['id']}/complete"
    assert service.store.snapshot() == frozen
    payload = {'request_id': 'late-complete', 'expected_version': before['occurrence']['version']}
    done = clients[0].post(url, json=payload)
    assert done.status_code == 200, done.text
    assert done.json()['occurrence']['status'] == 'completed'
    assert clients[0].post(url, json=payload).json() == done.json()
    stored = service.store.snapshot()['occurrences'][before['occurrence']['id']]
    assert stored['member_progress']['A']['completed_at'] == clock[0].isoformat()
    assert card(clients, task['id'])['read_only']
    assert not clients[0].get('/api/home/tasks?status=open').json()['items']


@pytest.mark.parametrize('weekly', [False, True])
@pytest.mark.parametrize('mode', ['all', 'any'])
def test_overdue_card_completion_preserves_permissions_rules_and_occurrence(api, weekly, mode):
    clients, service, users, clock = api
    item = {'title': '补勾家务', **({'recurrence': {'frequency': 'weekly', 'weekday': None}}
                              if weekly else {'due_date': '2026-10-24'})}
    task, rows = create((service, users, clock), inv=invocation(space='household', temporal='timed',
        ids=['A', 'B'], completion_mode=mode), items=[item])
    occurrence_id = rows[0]['id']
    clock[0] += timedelta(days=14)
    before = card(clients, task['id'], occurrence_id)
    assert before['capabilities'] == {'editable_fields': [], 'actions': ['complete']}
    url = f"/api/home/tasks/{task['id']}/occurrences/{occurrence_id}"
    frozen = service.store.snapshot()
    unauthorized = clients[2].post(url + '/complete', json={'request_id': 'other', 'expected_version': 1})
    assert unauthorized.status_code == 403
    stale = save(clients, before, occurrence_action={'action': 'complete', 'expected_version': 999})
    assert stale.status_code == 409 and stale.json()['error'] == 'version_conflict'
    mixed = save(clients, before, request_id='mixed', definition_patch={'title': '不能顺带修改'},
        occurrence_action={'action': 'complete', 'expected_version': 1})
    assert mixed.status_code == 409 and mixed.json()['error'] == 'task_card_expired'
    assert service.store.snapshot() == frozen
    done = save(clients, before, occurrence_action={'action': 'complete', 'expected_version': 1})
    assert done.status_code == 200, done.text
    result = done.json()
    assert result['resource']['instance_id'] == occurrence_id
    assert result['occurrence']['status'] == ('open' if mode == 'all' else 'completed')
    assert result['occurrence']['member_progress']['B']['status'] == 'open'
    assert result['read_only'] and not result['capabilities']['actions']
    assert clients[0].post(url + '/reopen', json={'request_id': 'late-reopen', 'expected_version': 2}).status_code == 409
    if mode == 'all':
        assert card(clients, task['id'], occurrence_id, actor=1)['capabilities']['actions'] == ['complete']
        last = clients[1].post(url + '/complete', json={'request_id': 'bob-late', 'expected_version': 2})
        assert last.status_code == 200 and last.json()['occurrence']['status'] == 'completed'
    stored = service.store.snapshot()['occurrences']
    assert all(o['status'] == 'open' for key, o in stored.items()
               if o['task_id'] == task['id'] and key != occurrence_id)


@pytest.mark.parametrize('action', ['cancel', 'skip', 'archive', 'pause'])
def test_overdue_completion_does_not_unfreeze_ended_or_paused_tasks(api, action):
    clients, service, users, clock = api
    task, rows = create((service, users, clock), inv=invocation(temporal='timed'),
        items=[{'title': '历史事项', 'recurrence': {'frequency': 'weekly', 'weekday': None}}])
    change((service, users, clock), task, action, occ=rows[0] if action in {'cancel', 'skip'} else None)
    clock[0] += timedelta(days=14)
    view = card(clients, task['id'], rows[0]['id'])
    assert view['read_only'] and not view['capabilities']['actions']
    response = save(clients, view, occurrence_action={'action': 'complete', 'expected_version': view['occurrence']['version']})
    assert response.status_code == 409


def test_bound_native_tool_can_complete_overdue_occurrence(api):
    _, service, users, clock = api
    task, rows = create((service, users, clock), inv=invocation(temporal='timed'),
        items=[{'title': '补记完成', 'due_date': '2026-10-24'}])
    clock[0] += timedelta(days=7)
    registry = ToolRegistry()
    context = {'user_id': users[0]['id'], 'request_id': 'native-late', 'session_id': 's', 'branch_id': 'main',
               'task_ref': {'task_id': task['id'], 'occurrence_id': rows[0]['id']}}
    register_family_task_tools(registry, service, lambda: users[0], lambda: context)
    result = asyncio.run(registry.invoke(ToolCall('late', 'family_task_complete', {
        'task_id': task['id'], 'occurrence_id': rows[0]['id'], 'expected_version': rows[0]['version']})))
    assert not result.error, result
    stored = service.store.snapshot()['occurrences'][rows[0]['id']]
    assert stored['status'] == 'completed'
    assert stored['completed_at'] == clock[0].isoformat()


def test_committed_retry_after_midnight_returns_receipt_without_new_write(api):
    clients, service, users, clock = api
    task, _ = create((service, users, clock), inv=invocation(temporal='timed'), items=[{'title': '今天', 'due_date': '2026-10-23'}])
    before = card(clients, task['id'])
    assert save(clients, before, definition_patch={'title': '已保存标题'}).status_code == 200
    count = len(service.store.snapshot()['events'])
    clock[0] += timedelta(days=1)
    repeated = save(clients, before, definition_patch={'title': '已保存标题'})
    assert repeated.status_code == 200
    assert repeated.json()['capabilities'] == {'editable_fields': [], 'actions': ['complete']}
    assert len(service.store.snapshot()['events']) == count


def test_undated_completed_memo_is_frozen_and_pending_memo_has_no_date_expiry(api):
    clients, service, users, clock = api
    task, _ = create((service, users, clock))
    clock[0] += timedelta(days=10)
    before = card(clients, task['id'])
    assert before['valid_until'] is None and not before['read_only']
    done = save(clients, before, occurrence_action={'action': 'complete', 'expected_version': before['occurrence']['version']})
    assert done.status_code == 200 and done.json()['read_only']
    assert save(clients, done.json(), request_id='new', definition_patch={'title': '不可改'}).status_code == 409


def test_old_weekly_card_does_not_retarget_and_tool_cannot_bypass(api):
    clients, service, users, clock = api
    task, occurrences = create((service, users, clock), inv=invocation(temporal='timed'),
        items=[{'title': '每周家务', 'recurrence': {'frequency': 'weekly', 'weekday': None}}])
    instance = occurrences[0]['id']
    before = card(clients, task['id'], instance)
    changed = save(clients, before, scope='future', definition_patch={'title': '下周的新标题'})
    assert changed.status_code == 200, changed.text
    assert changed.json()['occurrence']['title_snapshot'] == '每周家务'
    clock[0] += timedelta(days=7)
    old = card(clients, task['id'], instance)
    assert old['resource']['instance_id'] == instance
    assert old['capabilities'] == {'editable_fields': [], 'actions': ['complete']}
    registry = ToolRegistry()
    context = {'user_id': users[0]['id'], 'request_id': 'native-bypass', 'session_id': 's', 'branch_id': 'main',
               'task_ref': {'task_id': task['id'], 'occurrence_id': instance}}
    register_family_task_tools(registry, service, lambda: users[0], lambda: context)
    result = asyncio.run(registry.invoke(ToolCall('bypass', 'family_task_update', {'task_id': task['id'],
        'expected_version': changed.json()['task']['version'], 'patch': {'title': '不能改历史'}})))
    assert result.error == 'task_card_expired'


def test_current_occurrence_edit_and_single_to_weekly_alias(api):
    clients, service, users, clock = api
    task, _ = create((service, users, clock), inv=invocation(temporal='timed'), items=[{'title': '原来', 'due_date': '2026-10-24'}])
    initial = card(clients, task['id'])
    changed = save(clients, initial, definition_patch={'recurrence': {'frequency': 'weekly', 'weekday': 'SA'}})
    assert changed.status_code == 200, changed.text
    new = changed.json()
    assert new['task']['id'] == task['id']
    assert card(clients, task['id'], initial['resource']['instance_id'])['resource']['instance_id'] == new['resource']['instance_id']
    edited = save(clients, new, request_id='edit-period', scope='occurrence', occurrence_patch={'title': '仅本期标题'})
    assert edited.status_code == 200
    assert edited.json()['task']['title'] == '原来' and edited.json()['occurrence']['title_snapshot'] == '仅本期标题'


def test_conversion_and_reassignment_keep_only_current_member_progress(api):
    clients, service, users, clock = api
    task, rows = create((service, users, clock), inv=invocation('household', temporal='timed', ids=['A', 'B']),
                       items=[{'title': '共同处理', 'due_date': '2026-10-24'}])
    change((service, users, clock), task, 'complete', occ=rows[0])
    before = card(clients, task['id'])
    saved = save(clients, before, definition_patch={'assignee_ids': ['B'], 'completion_mode': 'any',
        'recurrence': {'frequency': 'weekly', 'weekday': 'SA'}, 'starts_on': '2026-10-24'})
    assert saved.status_code == 200, saved.text
    assert saved.json()['occurrence']['status'] == 'open'
    assert set(saved.json()['occurrence']['member_progress']) == {'B'}
    other = card(clients, task['id'], instance_id=before['resource']['instance_id'], actor=1)
    response = clients[1].patch(f"/api/home/tasks/{task['id']}/card", json={
        'request_id': 'own-completion', 'expected_task_version': other['task']['version'],
        'occurrence_id': other['resource']['instance_id'], 'expected_occurrence_version': other['occurrence']['version'],
        'scope': 'occurrence', 'occurrence_action': {'action': 'complete', 'expected_version': other['occurrence']['version']}})
    assert response.status_code == 200, response.text
    assert response.json()['occurrence']['status'] == 'completed'


def test_draft_creation_commit_replay_and_branch_authorization(api, monkeypatch):
    clients, service, _, clock = api
    session = clients[0].post('/api/sessions').json()
    monkeypatch.setattr(web_app, '_new_llm_client', lambda: FakeLLM([ToolCall('draft', 'family_timed_memo_create', {'items': [{'title': '去上海'}]})]))
    response = clients[0].post('/api/chat', json={'session_id': session['id'], 'message': '创建日程，去上海'})
    block = response.json()['messages'][-1]['ui_blocks'][0]
    assert block['mode'] == 'draft'
    url = '/api/home/task-drafts/' + block['resource']['id']
    params = {'session_id': session['id']}
    view = clients[0].get(url, params=params).json()
    assert view['mode'] == 'draft' and not service.store.snapshot()['tasks']
    assert clients[1].get(url, params=params).status_code in {403, 404}
    payload = {'request_id': 'draft-submit', 'expected_version': view['draft']['version'],
        'items': [{'title': '去上海', 'due_at': '2026-10-24T17:34:00+08:00'}],
        'space_type': 'personal', 'temporal_type': 'timed', 'assignee_ids': ['A']}
    result = clients[0].post(url + '/commit', params=params, json=payload)
    assert result.status_code == 200, result.text
    assert result.json()['mode'] == 'saved'
    assert clients[0].post(url + '/commit', params=params, json=payload).status_code == 200
    assert len(service.store.snapshot()['tasks']) == 1
    assert clients[0].get(url, params=params).json()['mode'] == 'saved'
    clock[0] += timedelta(days=2)
    late = clients[0].get(url, params=params).json()
    assert not late['read_only']
    assert late['capabilities'] == {'editable_fields': [], 'actions': ['complete']}


def test_draft_native_confirmation_preserves_original_card_reference(api, monkeypatch):
    clients, service, _, _ = api
    session = clients[0].post('/api/sessions').json()
    first = FakeLLM([ToolCall('draft', 'family_timed_memo_create', {'items': [{'title': '出门'}]})])
    monkeypatch.setattr(web_app, '_new_llm_client', lambda: first)
    response = clients[0].post('/api/chat', json={'session_id': session['id'], 'message': '创建日程，出门'})
    draft_id = response.json()['messages'][-1]['ui_blocks'][0]['resource']['id']
    monkeypatch.setattr(web_app, '_new_llm_client', lambda: FakeLLM([ToolCall('save', 'family_timed_memo_create', {'items': [{'title': '出门', 'due_date': '2026-10-24'}]})]))
    saved = clients[0].post('/api/chat', json={'session_id': session['id'], 'message': '明天下午5点'})
    assert saved.status_code == 200
    restored = clients[0].get('/api/home/task-drafts/' + draft_id, params={'session_id': session['id']})
    assert restored.status_code == 200 and restored.json()['mode'] == 'saved'
    assert len(service.store.snapshot()['tasks']) == 1


def test_draft_expiry_and_replaced_branch_are_readonly_or_rejected(api, monkeypatch):
    clients, service, _, clock = api
    session = clients[0].post('/api/sessions').json()
    monkeypatch.setattr(web_app, '_new_llm_client', lambda: FakeLLM([ToolCall('draft', 'family_timed_memo_create', {'items': [{'title': '出门'}]})]))
    response = clients[0].post('/api/chat', json={'session_id': session['id'], 'message': '创建日程，出门'})
    ref = response.json()['messages'][-1]['ui_blocks'][0]
    url = '/api/home/task-drafts/' + ref['resource']['id']
    clock[0] += timedelta(minutes=31)
    view = clients[0].get(url, params={'session_id': session['id']}).json()
    assert view['read_only'] and not view['capabilities']['actions']
    payload = {'request_id': 'late', 'expected_version': view['draft']['version'], 'items': [{'title': '出门', 'due_date': '2026-10-24'}], 'space_type': 'personal', 'temporal_type': 'timed'}
    assert clients[0].post(url + '/commit', params={'session_id': session['id']}, json=payload).status_code == 409
    assert not service.store.snapshot()['tasks']
    original = web_app.store.load_session(session['id'])
    web_app.store.save_messages(session['id'], original['messages'][:1])
    assert clients[0].get(url, params={'session_id': session['id']}).status_code == 404


def test_shared_session_card_cannot_move_to_personal(api):
    clients, service, users, clock = api
    task, _ = create((service, users, clock), inv=invocation('household'))
    session = clients[0].post('/api/sessions').json()
    assert clients[0].patch('/api/sessions/' + session['id'] + '/share', json={'scope': 'all'}).status_code == 200
    view = card(clients, task['id'])
    response = clients[0].patch(f"/api/home/tasks/{task['id']}/card", params={'session_id': session['id']}, json={
        'request_id': 'private-move', 'expected_task_version': view['task']['version'],
        'expected_occurrence_version': view['occurrence']['version'], 'occurrence_id': view['occurrence']['id'],
        'definition_patch': {'space_type': 'personal'}, 'audience_confirmed': True})
    assert response.status_code == 403
    assert service.get(users[0], task['id'])['task']['space_type'] == 'household'


def test_generic_presenter_can_register_another_domain_without_task_assumptions():
    presenter = CardPresenter()
    presenter.register('poll', {'family_poll'}, {'test_poll_create'})
    ref = {'type': 'interactive_card', 'schema_version': 1, 'kind': 'poll', 'mode': 'saved', 'card_id': 'test',
           'resource': {'type': 'family_poll', 'id': 'poll-1'}, 'html': '<script>bad()</script>'}
    result = ToolResult('call', 'test_poll_create', 'success', output={'ui_blocks': [ref]})
    actual = presenter.present(result)
    assert actual[0]['resource']['id'] == 'poll-1' and 'html' not in actual[0]
    assert presenter.present(ToolResult('call', 'unknown_tool', 'success', output={'ui_blocks': [ref]})) == []
    ref['schema_version'] = 999
    assert not presenter.present(result)
    ref['schema_version'] = 1
    ref['mode'] = 'executable'
    assert not presenter.present(result)
    ref['mode'] = 'saved'
    ref['resource'] = 'not-a-resource'
    assert not presenter.present(result)


def test_draft_literal_time_text_requires_a_deliberate_choice(api, monkeypatch):
    clients, service, _, _ = api
    session = clients[0].post('/api/sessions').json()
    monkeypatch.setattr(web_app, '_new_llm_client', lambda: FakeLLM([ToolCall('draft', 'family_undated_memo_create', {'items': [{'title': '明天买牛奶'}]})]))
    response = clients[0].post('/api/chat', json={'session_id': session['id'], 'message': '/ 备忘 明天买牛奶'})
    block = response.json()['messages'][-1]['ui_blocks'][0]
    url = '/api/home/task-drafts/' + block['resource']['id']
    params = {'session_id': session['id']}
    draft = clients[0].get(url, params=params).json()['draft']
    payload = {'request_id': 'literal', 'expected_version': draft['version'], 'items': draft['items'],
               'space_type': 'personal', 'temporal_type': 'undated', 'assignee_ids': ['A']}
    refused = clients[0].post(url + '/commit', params=params, json=payload)
    assert refused.status_code == 400 and not service.store.snapshot()['tasks']
    saved = clients[0].post(url + '/commit', params=params, json={**payload, 'literal_time_text': True})
    assert saved.status_code == 200, saved.text
    assert saved.json()['task']['temporal_type'] == 'undated' and saved.json()['task']['due_date'] is None


def test_completion_rule_recomputes_total_without_erasing_individual_progress(api):
    clients, service, users, clock = api
    task, rows = create((service, users, clock), inv=invocation('household', temporal='timed', ids=['A', 'B']),
                       items=[{'title': '共同处理', 'due_date': '2026-10-24'}])
    change((service, users, clock), task, 'complete', occ=rows[0])
    view = card(clients, task['id'])
    assert view['occurrence']['status'] == 'open'
    response = save(clients, view, definition_patch={'completion_mode': 'any'})
    assert response.status_code == 200, response.text
    assert response.json()['occurrence']['status'] == 'completed'
    assert response.json()['occurrence']['member_progress']['B']['status'] == 'open'
    other = card(clients, task['id'], actor=1)
    assert other['read_only'] and 'reopen' not in other['capabilities']['actions']


def test_native_card_binding_is_rechecked_after_waiting_for_transaction(api, monkeypatch):
    clients, service, users, clock = api
    task, rows = create((service, users, clock), inv=invocation(temporal='timed'),
                       items=[{'title': '周期', 'recurrence': {'frequency': 'weekly', 'weekday': 'FR'}}])
    context = {'user_id': users[0]['id'], 'request_id': 'late-native', 'session_id': 's', 'branch_id': 'main',
               'task_ref': {'task_id': task['id'], 'occurrence_id': rows[0]['id']}}
    registry = ToolRegistry()
    register_family_task_tools(registry, service, lambda: users[0], lambda: context)
    original = service.change
    def delayed(*args, **kwargs):
        clock[0] += timedelta(days=1)
        return original(*args, **kwargs)
    monkeypatch.setattr(service, 'change', delayed)
    result = asyncio.run(registry.invoke(ToolCall('late', 'family_task_update', {'task_id': task['id'],
        'expected_version': task['version'], 'patch': {'title': '不能越过截止时间'}})))
    assert result.error == 'task_card_expired'
    assert service.get(users[0], task['id'])['task']['title'] == '周期'


def test_followup_chat_binds_the_original_card_instance_after_a_new_week(api, monkeypatch):
    clients, service, _, clock = api
    session = clients[0].post('/api/sessions').json()
    monkeypatch.setattr(web_app, '_new_llm_client', lambda: FakeLLM([ToolCall('new', 'family_timed_memo_create',
        {'items': [{'title': '家务', 'recurrence': {'frequency': 'weekly', 'weekday': None}}]})]))
    result = clients[0].post('/api/chat', json={'session_id': session['id'], 'message': '创建每周日程，做家务'}).json()
    resource = result['messages'][-1]['ui_blocks'][0]['resource']
    clock[0] += timedelta(days=7)
    monkeypatch.setattr(web_app, '_new_llm_client', lambda: FakeLLM([ToolCall('update', 'family_task_update',
        {'task_id': resource['id'], 'expected_version': 1, 'patch': {'title': '不该修改'}})]))
    response = clients[0].post('/api/chat', json={'session_id': session['id'], 'message': '把这条的标题改一下'})
    assert 'task_card_expired' in response.text
    assert service.store.snapshot()['tasks'][resource['id']]['title'] == '家务'
