"""014: real authorization, time boundaries, image ownership and native card integration."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from unittest.mock import AsyncMock
from services.intent_router import IntentRouteResult
import json
import pytest
from PIL import Image

from agent_runtime import ToolCall
from services.board_service import BoardPostService
from services.board_store import BoardStore
from services.task_store import TaskError
from test_family_task_api import api, FakeLLM  # noqa: F401
import web_app


def data(**extra):
    return {'title': '晚饭', 'content_blocks': [{'type': 'text', 'text': '饭在冰箱里。'}],
            'audience_mode': 'selected', 'recipient_ids': ['B'], 'retention_mode': 'permanent', **extra}


@pytest.fixture
def board(family, tmp_path):
    tasks, users, clock = family
    return BoardPostService(BoardStore(tmp_path / 'board.json'), tasks.members, clock=lambda: clock[0]), users, clock


@pytest.fixture
def board_api(api, tmp_path, monkeypatch):
    clients, tasks, users, clock = api
    service = BoardPostService(BoardStore(tmp_path / 'board.json'), tasks.members, clock=lambda: clock[0])
    monkeypatch.setattr(web_app, 'family_board', service)
    # These tests exercise board tool execution, not the separate intent model.
    monkeypatch.setattr(web_app.intent_router, 'route', AsyncMock(return_value=
        IntentRouteResult(action='general_chat', source='test:board')))
    return clients, service, users, clock


def image_bytes():
    out = BytesIO()
    Image.new('RGB', (30, 20), '#abceef').save(out, 'PNG')
    return out.getvalue()


def test_selected_multi_all_and_revocation(board):
    service, users, _ = board
    saved = service.create(users[0], data(), request_id='publish')
    identifier = saved['post']['id']
    assert service.get(users[1], identifier)['read_only']
    with pytest.raises(TaskError, match='board_post_not_found'):
        service.get(users[2], identifier)
    assert not service.list(users[2])['items']
    with pytest.raises(TaskError, match='forbidden'):
        service.change(users[1], identifier, {'title': 'bad'}, request_id='bad', expected_version=1)
    service.change(users[0], identifier, {'recipient_ids': ['B', 'C', 'B']}, request_id='multi', expected_version=1)
    assert service.get(users[2], identifier)['post']['recipient_ids'] == ['B', 'C']
    service.change(users[0], identifier, {'audience_mode': 'household', 'recipient_ids': []}, request_id='all', expected_version=2)
    assert len(service.list(users[2])['items']) == 1
    service.change(users[0], identifier, {'audience_mode': 'selected', 'recipient_ids': ['C']}, request_id='revoke', expected_version=3)
    with pytest.raises(TaskError, match='board_post_not_found'):
        service.get(users[1], identifier)
    assert not service.list(users[1])['items']


def test_expiry_at_boundary_destroys_payload_and_retry_cannot_republish(board):
    service, users, clock = board
    fields = data(retention_mode='until', expires_at=(clock[0] + timedelta(seconds=5)).isoformat())
    saved = service.create(users[0], fields, request_id='once')
    clock[0] += timedelta(seconds=5)
    assert service.list(users[1])['items'] == []
    assert saved['post']['id'] not in service.store.snapshot()['posts']
    for user in users:
        with pytest.raises(TaskError, match='board_post_not_found'):
            service.get(user, saved['post']['id'])
    with pytest.raises(TaskError, match='board_post_not_found'):
        service.create(users[0], fields, request_id='once')
    with pytest.raises(TaskError, match='board_post_not_found'):
        service.change(users[0], saved['post']['id'], {'expires_at': None, 'retention_mode': 'permanent'}, request_id='bypass', expected_version=1)
    permanent = service.create(users[0], data(), request_id='long-term')
    clock[0] += timedelta(days=500)
    assert service.get(users[0], permanent['post']['id'])['post']['state'] == 'active'


def test_drafts_missing_fields_commit_once_duration_from_commit(board):
    service, users, clock = board
    saved = service.create(users[0], data(recipient_ids=[], retention_mode='until', expires_at=None), request_id='draft', draft=True)
    identifier = saved['post']['id']
    assert saved['post']['missing_fields'] == ['接收人', '截止时间']
    assert service.list(users[0])['items'] == []
    with pytest.raises(TaskError, match='board_draft_not_found'):
        service.get(users[1], identifier, draft=True)
    clock[0] += timedelta(minutes=15)
    args = {'recipient_ids': ['B'], 'duration_hours': 24}
    result = service.change(users[0], identifier, args, draft=True, action='publish', request_id='commit', expected_version=1)
    assert service._date(result['post']['expires_at']) == service.now() + timedelta(hours=24)
    assert service.change(users[0], identifier, args, draft=True, action='publish', request_id='commit', expected_version=1)['post']['id'] == result['post']['id']
    assert service.get(users[0], identifier, draft=True)['resource'] == result['resource']
    with pytest.raises(TaskError, match='draft_already_published'):
        service.change(users[0], identifier, {}, draft=True, action='publish', request_id='another', expected_version=2)
    assert len(service.store.snapshot()['posts']) == 1


def test_images_decode_and_do_not_leak_after_withdrawal(board):
    service, users, _ = board
    with pytest.raises(TaskError, match='invalid_board_image'):
        service.upload(users[0], b'<svg>executable</svg>')
    asset = service.upload(users[0], image_bytes())['asset_id']
    with pytest.raises(TaskError, match='board_asset_not_found'):
        service.asset(users[1], asset)
    saved = service.create(users[0], data(content_blocks=[{'type': 'image', 'asset_id': asset, 'alt': '照片'}]), request_id='pic')
    assert service.asset(users[1], asset).is_file()
    with pytest.raises(TaskError, match='board_asset_not_found'):
        service.create(users[1], data(content_blocks=[{'type': 'image', 'asset_id': asset}], recipient_ids=['A']), request_id='steal')
    service.change(users[0], saved['post']['id'], {}, request_id='withdraw', expected_version=1, action='withdraw')
    with pytest.raises(TaskError, match='board_asset_not_found'):
        service.asset(users[1], asset)
    assert service.asset(users[0], asset).is_file()


def test_concurrent_save_and_retry_share_one_ledger(board):
    service, users, _ = board
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _: service.create(users[0], data(), request_id='same'), range(5)))
    assert len({r['post']['id'] for r in results}) == 1
    identifier = results[0]['post']['id']
    service.change(users[0], identifier, {'title': 'new'}, request_id='edit', expected_version=1)
    before = service.store.snapshot()
    with pytest.raises(TaskError, match='version_conflict'):
        service.change(users[0], identifier, {'title': 'overwrite'}, request_id='other', expected_version=1)
    assert service.store.snapshot() == before
    with pytest.raises(TaskError, match='request_id_conflict'):
        service.create(users[0], data(title='different'), request_id='same')


def test_chat_draft_branch_and_session_protection(board):
    service, users, _ = board
    context = {'session_id': 's', 'branch_id': 'main', 'active_message_ids': ['u'], 'user_message_id': 'u'}
    saved = service.create(users[0], data(), draft=True, request_id='draft', context=context)
    with pytest.raises(TaskError, match='draft_session_required'):
        service.get(users[0], saved['post']['id'], draft=True)
    with pytest.raises(TaskError, match='board_draft_not_found'):
        service.get(users[0], saved['post']['id'], draft=True, context={**context, 'branch_id': 'other'})
    assert service.get(users[0], saved['post']['id'], draft=True, context=context)['mode'] == 'draft'
    with pytest.raises(TaskError, match='private_session_required'):
        service.create(users[0], data(audience_mode='household', recipient_ids=[]), request_id='shared', context={**context, 'shared': True})


def test_http_board_and_asset_authorization(board_api):
    clients, _, _, _ = board_api
    a, b, c = clients
    upload = a.post('/api/home/board/assets', files={'file': ('photo.png', image_bytes(), 'image/png')})
    assert upload.status_code == 201, upload.text
    asset = upload.json()['asset_id']
    payload = {'request_id': 'form', 'data': data(content_blocks=[{'type': 'image', 'asset_id': asset, 'alt': '图片'}])}
    response = a.post('/api/home/board/posts', json=payload)
    assert response.status_code == 201, response.text
    identifier = response.json()['post']['id']
    assert response.headers['cache-control'] == 'private, no-store'
    assert b.get('/api/home/board/assets/' + asset).status_code == 200
    assert c.get('/api/home/board/assets/' + asset).status_code == 404
    assert c.get('/api/home/board/posts/' + identifier + '/card').status_code == 404
    assert not c.get('/api/home/board/posts').json()['items']
    assert b.patch('/api/home/board/posts/' + identifier, json={'request_id': 'bad', 'expected_version': 1, 'data': {'title': 'bad'}}).status_code == 403
    assert a.post('/api/home/board/posts/' + identifier + '/withdraw', json={'request_id': 'withdraw', 'expected_version': 1}).status_code == 200
    assert b.get('/api/home/board/assets/' + asset).status_code == 404


@pytest.mark.parametrize('draft', [False, True])
def test_native_chat_cards_and_real_receipt(board_api, monkeypatch, draft):
    clients, service, _, _ = board_api
    session = clients[0].post('/api/sessions').json()
    call = ToolCall('create-board', 'family_board_post_create', {'data': data(audience_mode='household', recipient_ids=[])})
    monkeypatch.setattr(web_app, '_new_llm_client', lambda: FakeLLM([call]))
    raw = '帮我先写一张便笺，晚饭在冰箱里' if draft else '@ B 帮我发一张便笺，晚饭在冰箱里，长期保留'
    response = clients[0].post('/api/chat/stream', json={'session_id': session['id'], 'message': raw})
    assert response.status_code == 200, response.text
    events = [json.loads(line) for line in response.text.splitlines()]
    blocks = [b for e in events if e['type'] == 'ui_blocks' for b in e['blocks']]
    assert len(blocks) == 1, events
    assert blocks[0]['kind'] == 'board_post' and blocks[0]['mode'] == ('draft' if draft else 'saved')
    final = web_app.store.load_session(session['id'])['messages'][-1]
    assert final['ui_blocks'][0]['card_id'] == blocks[0]['card_id']
    assert ('尚未发布' if draft else '便笺已保存') in final['content']
    if draft:
        assert not service.store.snapshot()['posts']
        path = '/api/home/board/drafts/' + blocks[0]['resource']['id']
        assert clients[0].get(path).status_code == 403
        current = clients[0].get(path, params={'session_id': session['id']})
        assert current.status_code == 200, current.text
        committed = clients[0].post(path + '/commit', params={'session_id': session['id']}, json={'request_id': 'publish-card', 'expected_version': 1, 'data': {'recipient_ids': ['B']}})
        assert committed.status_code == 200, committed.text
    else:
        assert len(service.store.snapshot()['posts']) == 1
        saved = next(iter(service.store.snapshot()['posts'].values()))
        # Model attempted household sharing; only the user's B selection is used.
        assert saved['recipient_ids'] == ['B'] and saved['audience_mode'] == 'selected'
    assert clients[0].patch('/api/sessions/' + session['id'] + '/share', json={'scope': 'all'}).status_code == 400


def test_relative_retention_edit_and_expired_draft_cannot_bypass_time(board):
    service, users, clock = board
    saved = service.create(users[0], data(), request_id='published')
    changed = service.change(users[0], saved['post']['id'], {'retention_mode': 'until', 'duration_hours': 24, 'expires_at': None}, request_id='relative-edit', expected_version=1)
    assert changed['post']['expires_at'] == (service.now() + timedelta(hours=24)).isoformat()
    draft = service.create(users[0], {}, request_id='new-draft', draft=True)
    clock[0] += timedelta(minutes=30)
    with pytest.raises(TaskError, match='board_draft_not_found'):
        service.change(users[0], draft['post']['id'], data(), draft=True, action='publish', request_id='late', expected_version=1)


def test_media_import_retries_are_stable_and_orphan_cleanup_keeps_posts(board):
    service, users, clock = board
    first = service.upload(users[0], image_bytes())
    assert service.upload(users[0], image_bytes()) == first
    saved = service.create(users[0], data(content_blocks=[{'type': 'image', 'asset_id': first['asset_id']}]), request_id='image')
    orphan = service.upload(users[1], image_bytes())
    clock[0] += timedelta(days=2)
    service.upload(users[0], image_bytes())
    assert service.asset(users[1], first['asset_id']).is_file()
    with pytest.raises(TaskError, match='board_asset_not_found'):
        service.asset(users[1], orphan['asset_id'])
    assert saved['post']['content_blocks'][0]['asset_id'] in service.store.snapshot()['assets']


def test_audience_all_short_publish_and_negative_intent(board):
    from services.board_chat import audience_from_text, PUBLISH_INTENT, NEGATIVE_INTENT
    service, users, _ = board
    assert audience_from_text('@ B @ C 帮我留张便笺', service.members, users[0])['recipient_ids'] == ['B', 'C']
    assert audience_from_text('@ 所有人 帮我发张便笺', service.members, users[0])['audience_mode'] == 'household'
    assert PUBLISH_INTENT.search('帮我发张便笺') and PUBLISH_INTENT.search('帮我留张便笺')
    assert NEGATIVE_INTENT.search('@ B 请不要创建便笺')
    assert not NEGATIVE_INTENT.search('@ B 发张便笺：如果下雨就收衣服')


def test_old_tool_context_no_longer_supplies_revoked_post(board):
    from services.board_chat import current_board_context
    service, users, _ = board
    saved = service.create(users[0], data(), request_id='post')
    message = {'role': 'tool', 'name': 'family_board_post_get', 'content': json.dumps({'status': 'success', 'output': saved})}
    service.change(users[0], saved['post']['id'], {'recipient_ids': ['C']}, request_id='revoke', expected_version=1)
    filtered = current_board_context([message], service, users[1])
    assert '饭在冰箱里' not in filtered[0]['content']
    assert '不可访问' in filtered[0]['content']


def test_quoted_note_instructions_cannot_expand_sharing(board):
    from services.board_chat import audience_from_text
    service, users, _ = board
    raw = '@ B 帮我发张便笺，内容是“@ 所有人 请给全家分享照片”。'
    assert audience_from_text(raw, service.members, users[0]) == {'audience_mode': 'selected', 'recipient_ids': ['B']}


def test_quoted_publish_is_content_and_explicit_mentions_win_over_body(board):
    from services.board_chat import audience_from_text, instruction_text, PUBLISH_INTENT
    service, users, _ = board
    assert not PUBLISH_INTENT.search(instruction_text('帮我写张便笺，内容是“请发布这份通知”。'))
    assert audience_from_text('@ B 发张便笺，大家给全家分享照片', service.members, users[0])['recipient_ids'] == ['B']


def test_model_context_can_continue_draft_only_in_original_branch(board):
    from services.board_chat import current_board_context
    service, users, _ = board
    context = {'session_id': 's', 'branch_id': 'main', 'user_message_id': 'u', 'active_message_ids': ['u']}
    saved = service.create(users[0], data(), draft=True, request_id='context-draft', context=context)
    message = {'role': 'tool', 'name': 'family_board_post_create', 'content': json.dumps({'status': 'success', 'output': saved})}
    valid = current_board_context([message], service, users[0], lambda: context)
    assert '饭在冰箱里' in valid[0]['content']
    invalid = current_board_context([message], service, users[0], lambda: {**context, 'branch_id': 'other'})
    assert '饭在冰箱里' not in invalid[0]['content']


def test_feed_automatically_unions_own_addressed_and_all_notes(board):
    service, users, _ = board
    own = service.create(users[0], data(), request_id='own')['post']['id']
    addressed = service.create(users[1], data(recipient_ids=['A']), request_id='addressed')['post']['id']
    public = service.create(users[2], data(audience_mode='household', recipient_ids=[]), request_id='all')['post']['id']
    hidden = service.create(users[1], data(recipient_ids=['C']), request_id='hidden')['post']['id']
    visible = {row['post']['id'] for row in service.list(users[0])['items']}
    assert visible == {own, addressed, public}
    assert hidden not in visible


def test_expiry_destroys_images_copied_drafts_and_backups_but_keeps_live_references(board):
    service, users, clock = board
    asset = service.upload(users[0], image_bytes())['asset_id']
    deadline = (clock[0] + timedelta(seconds=5)).isoformat()
    draft = service.create(users[0], data(title='销毁专属文本', content_blocks=[{'type': 'text', 'text': '销毁专属文本'}, {'type': 'image', 'asset_id': asset}], retention_mode='until', expires_at=deadline), draft=True, request_id='draft-destroy')
    published = service.change(users[0], draft['post']['id'], {}, draft=True, action='publish', request_id='publish-destroy', expected_version=1)
    shared = service.create(users[0], data(title='长期照片', content_blocks=[{'type': 'image', 'asset_id': asset}]), request_id='live-photo')
    # Capture the draft before publication in an old backup; it must be erased
    # using the live draft ID even though that backup lacks its commit mapping.
    backup = service.store.path.parent / 'backups' / 'board-2000-01-01.json'
    before_commit = service.store.snapshot()
    before_commit['posts'].pop(published['post']['id'])
    before_commit['drafts'][draft['post']['id']].pop('committed_post_id')
    service.store.write_atomic(backup, before_commit)
    clock[0] += timedelta(seconds=5)
    result = service.cleanup_expired()
    assert result['destroyed_ids'] == [published['post']['id']]
    current = service.store.snapshot()
    assert draft['post']['id'] not in current['drafts']
    assert '销毁专属文本' not in service.store.path.read_text()
    for path in (service.store.path.parent / 'backups').glob('board-*.json'):
        assert '销毁专属文本' not in path.read_text()
    assert service.asset(users[1], asset).is_file()
    # Once its final live note expires, both metadata and file are destroyed.
    service.change(users[0], shared['post']['id'], {'retention_mode': 'until', 'expires_at': (clock[0] + timedelta(seconds=5)).isoformat()}, request_id='end-last', expected_version=1)
    clock[0] += timedelta(seconds=5)
    service.cleanup_expired()
    assert asset not in service.store.snapshot()['assets']
    assert not (service.asset_root / (asset + '.png')).exists()
    for user in users:
        with pytest.raises(TaskError, match='board_asset_not_found'):
            service.asset(user, asset)


def test_background_cleanup_runs_without_page_or_reminder_delivery(board_api, monkeypatch):
    import asyncio
    _, service, users, clock = board_api
    post = service.create(users[0], data(retention_mode='until', expires_at=(clock[0] + timedelta(seconds=1)).isoformat()), request_id='idle')['post']
    clock[0] += timedelta(seconds=1)
    async def stop_after_one_pass(_seconds):
        raise asyncio.CancelledError()
    monkeypatch.setattr(web_app.asyncio, 'sleep', stop_after_one_pass)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(web_app._board_cleanup_loop())
    assert post['id'] not in service.store.snapshot()['posts']


def test_http_old_filters_cannot_reveal_destroyed_note_or_its_image(board_api):
    clients, service, users, clock = board_api
    asset = service.upload(users[0], image_bytes())['asset_id']
    post = service.create(users[0], data(content_blocks=[{'type': 'image', 'asset_id': asset}], retention_mode='until', expires_at=(clock[0] + timedelta(seconds=1)).isoformat()), request_id='destroy-http')['post']
    clock[0] += timedelta(seconds=1)
    assert clients[0].get('/api/home/board/posts?state=expired&view=own').json()['items'] == []
    for client in clients:
        assert client.get('/api/home/board/posts/' + post['id']).status_code == 404
        assert client.get('/api/home/board/posts/' + post['id'] + '/card').status_code == 404
        assert client.get('/api/home/board/assets/' + asset).status_code == 404


def test_publish_rejects_metadata_without_saved_image_and_retry_can_repair(board):
    service, users, _ = board
    asset = service.upload(users[0], image_bytes())['asset_id']
    draft = service.create(users[0], data(content_blocks=[{'type': 'image', 'asset_id': asset}]), draft=True, request_id='missing-file-draft')
    path = service.asset_root / (asset + '.png')
    path.unlink()
    with pytest.raises(TaskError, match='board_asset_not_found'):
        service.change(users[0], draft['post']['id'], {}, draft=True, action='publish', request_id='missing-file-commit', expected_version=1)
    assert not service.store.snapshot()['posts']
    assert service.upload(users[0], image_bytes())['asset_id'] == asset
    result = service.change(users[0], draft['post']['id'], {}, draft=True, action='publish', request_id='missing-file-commit', expected_version=1)
    assert result['post']['content_blocks'][0]['asset_id'] == asset
    assert service.asset(users[1], asset).read_bytes() == path.read_bytes()


def test_image_previews_are_small_and_keep_authorization_and_withdrawal(board_api):
    clients, service, users, _ = board_api
    a, b, c = clients
    # A deterministic textured image exercises real image encoding/transfer size.
    import random
    rng = random.Random(42)
    original = Image.frombytes('RGB', (1200, 900), rng.randbytes(1200 * 900 * 3))
    data_stream = BytesIO()
    original.save(data_stream, format='JPEG', quality=90)
    asset = a.post('/api/home/board/assets', files={'file': ('photo.jpg', data_stream.getvalue(), 'image/jpeg')}).json()['asset_id']
    post = a.post('/api/home/board/posts', json={'request_id': 'preview-photo', 'data': data(content_blocks=[{'type': 'image', 'asset_id': asset}])}).json()['post']
    raw = b.get('/api/home/board/assets/' + asset)
    small = b.get('/api/home/board/assets/' + asset + '?width=640')
    assert small.status_code == 200
    assert small.headers['cache-control'] == 'private, no-store'
    assert small.headers['content-type'] == 'image/jpeg'
    assert len(small.content) < len(raw.content) / 3
    with Image.open(BytesIO(small.content)) as preview:
        assert max(preview.size) <= 640
    assert c.get('/api/home/board/assets/' + asset + '?width=640').status_code == 404
    assert b.get('/api/home/board/assets/' + asset + '?width=100000').status_code == 422
    a.post('/api/home/board/posts/' + post['id'] + '/withdraw', json={'request_id': 'preview-withdraw', 'expected_version': 1})
    assert b.get('/api/home/board/assets/' + asset + '?width=640').status_code == 404
