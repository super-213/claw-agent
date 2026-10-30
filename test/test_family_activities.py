"""016: real members, transaction boundaries, destructive retention and native tools."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from copy import deepcopy
import json
import pytest
from services.family_activity_store import FamilyActivityStore
from services.family_activity_service import FamilyActivityService
from services.task_store import TaskError
from test_family_task_api import api  # noqa: F401
import web_app


@pytest.fixture
def activities(family, tmp_path):
    tasks, users, clock = family
    return FamilyActivityService(FamilyActivityStore(tmp_path / 'family-activities.json'), tasks.members,
                                 clock=lambda: clock[0]), users, clock


@pytest.fixture
def activity_api(api, monkeypatch, tmp_path):
    clients, tasks, users, clock = api
    service = FamilyActivityService(FamilyActivityStore(tmp_path / 'family-activities.json'), tasks.members, clock=lambda: clock[0])
    monkeypatch.setattr(web_app, 'family_activities', service)
    from services.board_service import BoardPostService
    from services.board_store import BoardStore
    monkeypatch.setattr(web_app, 'family_board', BoardPostService(BoardStore(tmp_path / 'board.json'), tasks.members, clock=lambda: clock[0]))
    return clients, service, users, clock


def create(service, user, kind='poll', rid='create', **extra):
    return service.create(user, kind, {'title': '周末安排', **({'options': ['火锅', '烧烤']} if kind == 'poll' else {}), **extra}, request_id=rid)


def participate(service, user, view, rid='vote', ids=None, **extra):
    return service.change(user, view['activity']['kind'], view['resource']['id'], 'participate',
        data={'option_ids': ids or ['option_1']} if view['activity']['kind'] == 'poll' else {'values': {'content': '一份'}},
        request_id=rid, participation_version=view['participation_version'], **extra)


def test_all_completed_notifies_once_and_freezes(activities):
    service, users, clock = activities
    saved = create(service, users[0], participation_deadline_at=(clock[0] + timedelta(hours=1)).isoformat())
    identifier = saved['resource']['id']
    for index, user in enumerate(users):
        result = participate(service, user, service.get(user, 'poll', identifier), rid=str(index))
        assert result['activity']['state'] == ('closed' if index == 2 else 'open')
    assert result['activity']['close_reason'] == 'all_completed'
    assert result['activity']['counts'] == {'option_1': 3, 'option_2': 0}
    assert len(service.notifications(users[0])) == 1
    assert service.notifications(users[1]) == []
    clock[0] += timedelta(hours=2)
    service.cleanup_expired()
    assert len(service.notifications(users[0])) == 1
    with pytest.raises(TaskError, match='activity_closed'):
        service.change(users[0], 'poll', identifier, 'save', data={'participation_deadline_at': None}, request_id='reopen', expected_version=1)


def test_deadline_vs_destruction_and_backups(activities):
    service, users, clock = activities
    saved = create(service, users[0], participation_deadline_at=(clock[0] + timedelta(seconds=5)).isoformat(), expires_at=(clock[0] + timedelta(seconds=10)).isoformat())
    identifier = saved['resource']['id']
    participate(service, users[0], saved)
    snapshot = service.store.snapshot()
    clock[0] += timedelta(seconds=5)
    assert service.get(users[1], 'poll', identifier)['activity']['close_reason'] == 'deadline'
    with pytest.raises(TaskError, match='activity_closed'):
        participate(service, users[1], saved)
    clock[0] += timedelta(seconds=5)
    service.cleanup_expired()
    assert service.notifications(users[0]) == []
    with pytest.raises(TaskError, match='activity_not_found'):
        service.get(users[0], 'poll', identifier)
    assert not service.store.snapshot()['participations']
    for path in (service.store.path.parent / 'backups').glob('*.json'):
        assert '火锅' not in path.read_text()
    # Restoring an old ledger cannot bypass the independent destruction journal.
    service.store.write_atomic(service.store.path, snapshot)
    with pytest.raises(TaskError, match='activity_not_found'):
        service.get(users[0], 'poll', identifier)
    assert '火锅' not in service.store.path.read_text()


def test_draft_commit_idempotent_and_no_content_copy(activities):
    service, users, clock = activities
    context = {'session_id': 's', 'branch_id': 'main', 'user_message_id': 'm', 'active_message_ids': ['m']}
    draft = service.create(users[0], 'poll', {'retention_duration_hours': 24}, draft=True, request_id='draft', context=context)
    identifier = draft['resource']['id']
    assert draft['activity']['missing_fields'] == ['标题', '至少两个投票选项']
    assert not service.list(users[1])
    for user, ctx in [(users[1], context), (users[0], {**context, 'branch_id': 'other'}), (users[0], None)]:
        with pytest.raises(TaskError, match='activity_not_found'):
            service.get(user, 'poll', identifier, draft=True, context=ctx)
    clock[0] += timedelta(hours=2)
    args = dict(data={'title': '周末', 'options': ['火锅', '烧烤']}, request_id='commit', expected_version=1, draft=True, context=context)
    committed = service.change(users[0], 'poll', identifier, 'publish', **args)
    assert service.date(committed['activity']['expires_at']) == service.now() + timedelta(hours=24)
    assert service.change(users[0], 'poll', identifier, 'publish', **args)['resource'] == committed['resource']
    assert 'options' not in service.store.snapshot()['drafts'][identifier]
    assert len(service.list(users[1])) == 1
    with pytest.raises(TaskError, match='draft_already_published'):
        service.change(users[0], 'poll', identifier, 'publish', **{**args, 'request_id': 'another'})


def test_capacity_concurrent_and_stable_sequence(activities):
    service, users, _ = activities
    saved = create(service, users[0], 'relay', capacity=2, auto_close=False)
    identifier = saved['resource']['id']
    def join(user):
        try:
            return participate(service, user, saved, rid=user['id'])
        except TaskError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(join, users))
    assert results.count('activity_closed') == 1
    result = service.get(users[0], 'relay', identifier)
    assert [p['sequence'] for p in result['participants']] == [1, 2]
    assert result['activity']['close_reason'] == 'capacity'


def test_relay_withdraw_rejoin_and_own_versions(activities):
    service, users, _ = activities
    saved = create(service, users[0], 'relay', auto_close=False)
    identifier = saved['resource']['id']
    first = participate(service, users[0], saved)
    participate(service, users[1], saved)
    changed = participate(service, users[0], first, rid='edit')
    assert changed['own_participation']['sequence'] == 1
    with pytest.raises(TaskError, match='version_conflict'):
        participate(service, users[0], first, rid='stale')
    gone = service.change(users[0], 'relay', identifier, 'withdraw', request_id='withdraw', participation_version=2)
    rejoin = participate(service, users[0], gone, rid='rejoin')
    assert rejoin['own_participation']['sequence'] == 3
    with pytest.raises(TaskError, match='activity_definition_frozen'):
        service.change(users[0], 'relay', identifier, 'save', data={'fields': [{'id': 'other', 'label': '其他', 'type': 'text', 'required': True}]}, request_id='fields', expected_version=1)


def test_vote_rules_and_permissions(activities):
    service, users, _ = activities
    saved = create(service, users[0], multiple=True, max_choices=2, allow_change=False)
    first = participate(service, users[1], saved, ids=['option_1', 'option_2'])
    with pytest.raises(TaskError, match='vote_change_forbidden'):
        participate(service, users[1], first, rid='revote')
    with pytest.raises(TaskError, match='invalid_vote'):
        participate(service, users[2], saved, ids=['option_1', 'option_1'])
    with pytest.raises(TaskError, match='forbidden'):
        service.change(users[1], 'poll', saved['resource']['id'], 'delete', request_id='delete', expected_version=1)
    with pytest.raises(TaskError, match='private_session_required'):
        service.get(users[0], 'poll', saved['resource']['id'], context={'session_id': 's', 'shared': True})
    with pytest.raises(TaskError, match='read_only_session'):
        service.change(users[0], 'poll', saved['resource']['id'], 'close', request_id='readonly', expected_version=1, context={'read_only_session': True})


def test_delete_cleans_backups_prevents_replay(activities):
    service, users, _ = activities
    saved = create(service, users[0])
    identifier = saved['resource']['id']
    snapshot = deepcopy(service.store.snapshot())
    args = dict(request_id='delete', expected_version=1)
    assert service.change(users[0], 'poll', identifier, 'delete', **args)['destroyed']
    assert service.change(users[0], 'poll', identifier, 'delete', **args)['destroyed']
    service.cleanup_expired()
    for path in (service.store.path.parent / 'backups').glob('*.json'):
        assert '火锅' not in path.read_text()
    with pytest.raises(TaskError, match='activity_not_found'):
        create(service, users[0])
    service.store.write_atomic(service.store.path, snapshot)
    assert not service.list(users[0])


def test_extend_retention_does_not_destroy_from_old_backup(activities):
    service, users, clock = activities
    saved = create(service, users[0], expires_at=(clock[0] + timedelta(hours=1)).isoformat())
    identifier = saved['resource']['id']
    service.change(users[0], 'poll', identifier, 'save', data={'expires_at': (clock[0] + timedelta(hours=5)).isoformat()}, expected_version=1, request_id='extend')
    clock[0] += timedelta(hours=2)
    assert service.get(users[0], 'poll', identifier)['activity']['state'] == 'open'


@pytest.mark.parametrize('patch,code', [({'participation_deadline_at': '2026-10-23T13:00'}, 'invalid_activity_time'), ({'expires_at': '2026-10-23T13:00:00+08:00', 'participation_deadline_at': '2026-10-23T14:00:00+08:00'}, 'activity_time_order'), ({'max_choices': 0}, 'invalid_poll_limits')])
def test_invalid_times_and_limits(activities, patch, code):
    service, users, _ = activities
    with pytest.raises(TaskError, match=code):
        create(service, users[0], **patch)


def test_membership_completion_and_notifications_disabled(activities):
    service, users, _ = activities
    saved = create(service, users[0], notify_creator=False)
    participate(service, users[0], saved)
    participate(service, users[1], saved)
    service.members.update('C', {'status': 'disabled'}, users[0])
    assert service.get(users[0], 'poll', saved['resource']['id'])['activity']['state'] == 'closed'
    assert not service.notifications(users[0])
    with pytest.raises(TaskError):
        service.get(users[2], 'poll', saved['resource']['id'])


def test_http_feed_notifications_and_cross_member(activity_api):
    clients, service, users, clock = activity_api
    created = clients[0].post('/api/home/polls', json={'request_id': 'api', 'data': {'title': '周末', 'options': ['火锅', '烧烤'], 'auto_close': False, 'participation_deadline_at': (clock[0] + timedelta(seconds=5)).isoformat()}})
    assert created.status_code == 201, created.text
    identifier = created.json()['resource']['id']
    for client in clients:
        response = client.get('/api/home/board/feed')
        assert response.status_code == 200, response.text
        assert response.json()['items'][0]['resource']['id'] == identifier
    response = clients[1].put(f'/api/home/polls/{identifier}/my-vote', json={'request_id': 'b', 'participation_version': 0, 'data': {'option_ids': ['option_1']}})
    assert response.status_code == 200, response.text
    assert clients[1].request('DELETE', '/api/home/polls/' + identifier, json={'request_id': 'bad', 'expected_version': 1}).status_code == 403
    clock[0] += timedelta(seconds=5)
    service.cleanup_expired()
    notices = clients[0].get('/api/home/notifications').json()['notifications']
    assert len(notices) == 1
    assert clients[1].get('/api/home/notifications').json()['notifications'] == []
    assert clients[0].post('/api/home/notifications/' + notices[0]['id'] + '/read').status_code == 200
    assert not clients[0].get('/api/home/notifications?unread_only=true').json()['notifications']


def test_native_plugins_have_real_refs_minimal_receipts_and_idempotence(activities):
    from agent_runtime.family_activity_tools import register_activity_tools
    from agent_runtime.plugins.contracts import ToolBindingContext
    from agent_runtime.registry import ToolRegistry
    service, users, _ = activities
    context = {'user_id': users[0]['id'], 'request_id': 'native', 'raw_input': '发起家庭投票，火锅还是烧烤'}
    binding = ToolBindingContext(runtime='web', get_user=lambda: users[0], get_execution_context=lambda: context)
    registry = ToolRegistry()
    register_activity_tools(registry, service, binding, 'poll')
    tool = registry.get('family_poll_create')
    result = tool.handler({'data': {'title': '聚餐', 'options': [{'text': '火锅'}, {'text': '烧烤'}]}})
    assert result['state'] == 'open'
    assert result['ui_blocks'][0]['kind'] == 'poll'
    assert '火锅' not in json.dumps(result, ensure_ascii=False)
    assert tool.handler({'data': {'title': '聚餐', 'options': [{'text': '火锅'}, {'text': '烧烤'}]}})['resource'] == result['resource']
    assert service.get(users[1], 'poll', result['resource']['id'])['activity']['title'] == '聚餐'
    fetched = registry.get('family_poll_get').handler({'activity_id': result['resource']['id']})
    assert fetched['options'][1] == {'id': 'option_2', 'text': '烧烤'}


def test_native_chat_sdk_loading_cards_persistence_and_destroy_scrubbing(activity_api, monkeypatch):
    from unittest.mock import AsyncMock
    from services.intent_router import IntentRouteResult
    from test_family_task_api import FakeLLM
    from agent_runtime import ToolCall
    from services.family_activity_privacy import sanitize_activity_history, cleanup_activity_history
    clients, service, users, _ = activity_api
    schemas_seen = []
    class Model(FakeLLM):
        async def achat_with_tools(self, messages, schemas):
            schemas_seen.append([s['function']['name'] for s in schemas])
            return await super().achat_with_tools(messages, schemas)
    monkeypatch.setattr(web_app, '_new_llm_client', lambda: Model([ToolCall('poll-native', 'family_poll_create', {'data': {'title': '合成活动标题', 'options': [{'text': '合成甲'}, {'text': '合成乙'}]}})]))
    monkeypatch.setattr(web_app.intent_router, 'route', AsyncMock(return_value=IntentRouteResult(action='general_chat', source='test:activities')))
    web_app.run_store.sanitize_persistence = lambda value: sanitize_activity_history(value, service.store.destroyed())
    web_app.store.sanitize_persistence = lambda value: sanitize_activity_history(value, service.store.destroyed())
    sid = clients[0].post('/api/sessions').json()['id']
    response = clients[0].post('/api/chat', json={'session_id': sid, 'request_id': 'native-http', 'message': '发起家庭投票，比较两种合成方案'})
    assert response.status_code == 200, response.text
    assert response.json()['run_status'] == 'completed', response.text
    assert 'family_poll_create' not in schemas_seen[0] and 'tool_load' in schemas_seen[0]
    assert any('family_poll_create' in names for names in schemas_seen[1:])
    session = clients[0].get('/api/sessions/' + sid).json()
    ref = session['messages'][-1]['ui_blocks'][0]
    assert ref['kind'] == 'poll'
    identifier = ref['resource']['id']
    assert clients[1].get('/api/home/polls/' + identifier).status_code == 200
    assert clients[0].patch('/api/sessions/' + sid + '/share', json={'scope': 'all'}).status_code == 400
    assert '合成甲' in web_app.store._path(sid).read_text()
    service.change(users[0], 'poll', identifier, 'delete', expected_version=1, request_id='delete')
    cleanup_activity_history(service, web_app.run_store, web_app.store)
    assert '合成甲' not in web_app.store._path(sid).read_text()
    for path in web_app.run_store.root_dir.glob('*.json'):
        assert '合成甲' not in path.read_text()
    gone = clients[0].get('/api/home/polls/' + identifier)
    assert gone.status_code == 404
    # A late writer also uses the persistence callback; original user text survives.
    web_app.store._write_session(sid, session)
    cleaned = web_app.store._path(sid).read_text()
    assert '合成甲' not in cleaned and '比较两种合成方案' in cleaned


def test_push_outbox_claim_retry_and_destroy_cancel(activities, tmp_path):
    from types import SimpleNamespace
    from unittest.mock import Mock
    import sqlite3
    from services.family_activity_notifications import deliver_activity_notifications
    service, users, clock = activities
    database = tmp_path / 'push.sqlite'
    def db():
        connection = sqlite3.connect(database)
        connection.row_factory = sqlite3.Row
        return connection
    with db() as connection:
        connection.execute('CREATE TABLE chat_devices(id TEXT,user_id TEXT,auth_hash TEXT,subscription TEXT,enabled INTEGER)')
        connection.execute('INSERT INTO chat_devices VALUES(?,?,?,?,1)', ('device', users[0]['id'], 'auth', '{}'))
    saved = create(service, users[0], participation_deadline_at=(clock[0] + timedelta(seconds=1)).isoformat(), expires_at=(clock[0] + timedelta(seconds=10)).isoformat())
    clock[0] += timedelta(seconds=1)
    transport = SimpleNamespace(store=SimpleNamespace(db=db), auth_valid=lambda *args: True, sender=Mock())
    deliver_activity_notifications(service, transport)
    deliver_activity_notifications(service, transport)
    assert transport.sender.call_count == 1
    payload = transport.sender.call_args.args[1]
    assert payload['url'].endswith(saved['resource']['id'])
    assert '周末安排' not in json.dumps(payload, ensure_ascii=False)
    clock[0] += timedelta(seconds=9)
    deliver_activity_notifications(service, transport)
    assert not service.notifications(users[0])
    assert transport.sender.call_count == 1


def test_native_draft_request_not_to_publish_and_missing_time(activities):
    from agent_runtime.family_activity_tools import register_activity_tools
    from agent_runtime.plugins.contracts import ToolBindingContext
    from agent_runtime.registry import ToolRegistry
    service, users, _ = activities
    context = {'user_id': users[0]['id'], 'request_id': 'draft-native', 'raw_input': '先拟一个家庭投票草稿，参与截止时间稍后在卡片选择，现在不要发布。'}
    binding = ToolBindingContext(runtime='web', get_user=lambda: users[0], get_execution_context=lambda: context)
    registry = ToolRegistry()
    register_activity_tools(registry, service, binding, 'poll')
    result = registry.get('family_poll_create').handler({'data': {'title': '晚餐', 'options': [{'text': '米饭'}, {'text': '面条'}]}})
    assert result['mode'] == 'draft'
    assert result['missing_fields'] == ['参与截止时间']
    assert not service.list(users[0])


def test_background_lifecycle_without_any_reader(activities, monkeypatch):
    import asyncio
    service, users, clock = activities
    saved = create(service, users[0], participation_deadline_at=(clock[0] + timedelta(seconds=1)).isoformat(), expires_at=(clock[0] + timedelta(seconds=2)).isoformat())
    identifier = saved['resource']['id']
    monkeypatch.setattr(web_app, 'family_activities', service)
    monkeypatch.setattr(web_app, 'cleanup_activity_history', lambda *args: None)
    monkeypatch.setattr(web_app, 'deliver_activity_notifications', lambda *args: None)
    monkeypatch.setattr(web_app, '_chat_background', lambda: type('Background', (), {'notifications': None, 'store': None})())
    async def stop_after_scan(*args):
        raise asyncio.CancelledError()
    monkeypatch.setattr(web_app.asyncio, 'sleep', stop_after_scan)
    for seconds in (1, 1):
        clock[0] += timedelta(seconds=seconds)
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(web_app._activity_lifecycle_loop())
        raw = json.loads(service.store.path.read_text())
        if identifier in raw['activities']:
            assert raw['activities'][identifier]['state'] == 'closed'
            assert len(raw['notifications']) == 1
        else:
            assert not raw['notifications'] and not raw['publications']
    assert identifier not in raw['activities']


def test_feed_keyset_pagination_and_custom_relay_fields(activity_api):
    clients, service, users, _ = activity_api
    for index in range(4):
        create(service, users[0], 'poll' if index % 2 else 'relay', rid='p' + str(index))
    first = clients[1].get('/api/home/board/feed?limit=2').json()
    second = clients[1].get('/api/home/board/feed', params={'limit': 2, 'cursor': first['next_cursor']}).json()
    assert len({v['resource']['id'] for v in first['items'] + second['items']}) == 4
    assert second['next_cursor'] is None
    assert clients[0].get('/api/home/board/feed?cursor=invalid').status_code == 400
    saved = create(service, users[0], 'relay', rid='custom', auto_close=False,
                   fields=[{'id': 'name', 'label': '物品', 'type': 'text', 'required': True}, {'id': 'qty', 'label': '数量', 'type': 'number', 'required': True}])
    identifier = saved['resource']['id']
    for values, code in [({'name': '  ', 'qty': 1}, 'relay_field_required'), ({'name': '牛奶', 'qty': '2'}, 'invalid_relay_entry')]:
        with pytest.raises(TaskError, match=code):
            service.change(users[1], 'relay', identifier, 'participate', data={'values': values}, request_id='invalid' + code, participation_version=0)
    result = service.change(users[1], 'relay', identifier, 'participate', data={'values': {'name': '牛奶', 'qty': 2}}, request_id='valid', participation_version=0)
    assert result['participants'][0]['values']['qty'] == 2


def test_background_event_arguments_are_scrubbed_at_expiry_before_sweep(activities, tmp_path):
    from services.chat_jobs import ChatJobStore
    from services.family_activity_privacy import sanitize_activity_history
    service, users, clock = activities
    saved = create(service, users[0], expires_at=(clock[0] + timedelta(seconds=1)).isoformat())
    identifier = saved['resource']['id']
    jobs = ChatJobStore(tmp_path / 'jobs.sqlite')
    jobs.sanitize_persistence = lambda value: sanitize_activity_history(value, service.store.private_unavailable())
    job, _ = jobs.create(users[0]['id'], 'session', 'activity-background', {'message': '原始聊天单独保留'})
    call = {'id': 'call-background', 'name': 'family_poll_create', 'arguments': {'data': {'title': '派生隐私标题'}}}
    jobs.append(job['id'], {'type': 'model_done', 'tool_calls': [call]})
    jobs.append(job['id'], {'type': 'tool_result', 'tool_result': {'call_id': 'call-background', 'name': 'family_poll_create', 'output': {'resource': saved['resource']}}})
    assert '派生隐私标题' in json.dumps(jobs.events(job['id'], 0), ensure_ascii=False)
    clock[0] += timedelta(seconds=1)
    assert identifier in json.loads(service.store.path.read_text())['activities']
    assert '派生隐私标题' not in json.dumps(jobs.events(job['id'], 0), ensure_ascii=False)
    jobs.append(job['id'], {'type': 'model_done', 'tool_calls': [call]})
    assert '派生隐私标题' not in json.dumps(jobs.events(job['id'], 0), ensure_ascii=False)
    assert '原始聊天单独保留' in jobs.get(job['id'], users[0]['id'])['payload']
