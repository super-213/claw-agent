from concurrent.futures import ThreadPoolExecutor

import pytest

from services.knowledge_service import KnowledgeService
from services.task_store import TaskError
from services.knowledge_context import fresh_knowledge_context


@pytest.fixture
def library(family, tmp_path):
    tasks, users, _ = family
    return KnowledgeService(tmp_path / 'knowledge', tasks.members), users


def document(library, tmp_path, text='清洗滤网：断电后取出滤网，用清水冲洗并晾干。', **kwargs):
    service, users = library
    path = tmp_path / 'manual.txt'
    path.write_text(text)
    return service.save_document(users[0], path, request_id=kwargs.pop('request_id', 'save'),
        title=kwargs.pop('title', '客厅空调说明书'), object_name='客厅空调', **kwargs)


def test_document_persists_long_tail_and_citable_source(library, tmp_path):
    service, users = library
    row = document(library, tmp_path, text='前言和使用说明。' * 5000 + '\n故障码 Z981 表示排水堵塞，请检查排水管。')
    reboot = KnowledgeService(service.root, service.members)
    matches = reboot.search(users[0], 'Z981')['items']
    assert matches and '排水堵塞' in matches[0]['text']
    assert matches[0]['version'] == 1
    source = reboot.source(users[0], 'documents', row['id'], 1, int(matches[0]['source_url'].split('chunk=')[1]))
    assert 'Z981' in source['chunk']['text']
    assert reboot.file_path(users[0], row['id'])[0].read_text().endswith('排水管。')


def test_private_shared_revoke_and_owner_permissions(library, tmp_path):
    service, (alice, bob, carol) = library
    row = document(library, tmp_path)
    assert service.search(bob, '滤网')['items'] == []
    with pytest.raises(TaskError, match='knowledge_not_found'):
        service.file_path(bob, row['id'])
    shared = service.change(alice, 'documents', row['id'], {'visibility': 'household'}, expected_version=1, request_id='share')
    assert service.search(bob, '过滤网')['items']
    with pytest.raises(TaskError, match='knowledge_owner_required'):
        service.change(bob, 'documents', row['id'], {'visibility': 'personal'}, expected_version=2, request_id='steal')
    service.members.update('B', {'status': 'disabled'}, alice)
    assert not service.search(bob, '滤网')['items']
    service.change(alice, 'documents', row['id'], {'visibility': 'personal'}, expected_version=shared['version'], request_id='revoke')
    assert not service.search(carol, '滤网')['items']


def test_unbound_personal_use_requires_no_family_setup(library, tmp_path):
    service, users = library
    outsider = service.members.users.create_user(username='outsider', password='secret123')
    row = service.save_record(outsider, request_id='save', title='钥匙', content='钥匙在玄关抽屉')
    assert service.search(outsider, '钥匙')['items']
    with pytest.raises(TaskError, match='member_not_bound'):
        service.change(outsider, 'records', row['id'], {'visibility': 'household'}, expected_version=1, request_id='share')
    assert not service.search(users[0], '钥匙')['items']  # Admin has no implicit library access.


def test_replace_deactivate_delete_and_version_conflict(library, tmp_path):
    service, users = library
    row = document(library, tmp_path, text='错误码 OLD900，请联系售后。')
    old_path, _ = service.file_path(users[0], row['id'])
    new_path = tmp_path / 'replacement.txt'
    new_path.write_text('错误码 NEW800，请清洁排水管。')
    new = service.save_document(users[0], new_path, request_id='replace', title=row['title'], replace_id=row['id'], expected_version=1)
    assert new['id'] == row['id'] and new['version'] == 2
    assert not old_path.exists()
    assert not service.search(users[0], 'OLD900')['items']
    assert service.search(users[0], 'NEW800')['items']
    with pytest.raises(TaskError, match='version_conflict'):
        service.source(users[0], 'documents', row['id'], 1)
    with pytest.raises(TaskError, match='version_conflict'):
        service.change(users[0], 'documents', row['id'], {'title': '过期写入'}, expected_version=1, request_id='conflict')
    removed = service.change(users[0], 'documents', row['id'], {}, expected_version=2, request_id='delete', delete=True)
    assert '原上传文件' in removed['deletion_note']
    assert new_path.exists()
    assert not service.search(users[0], 'NEW800')['items']
    assert not list(service.blobs.iterdir())


def test_records_correction_events_duplicates_and_shared_conflicts(library):
    service, users = library
    row = service.save_record(users[0], request_id='key', title='备用钥匙位置', content='备用钥匙在玄关第二层抽屉', object_name='备用钥匙')
    same = service.save_record(users[0], request_id='key-again', title=row['title'], content=row['content'], object_name='备用钥匙')
    assert same['id'] == row['id']
    shared = service.change(users[0], 'records', row['id'], {'visibility': 'household'}, expected_version=1, request_id='share')
    fixed = service.change(users[1], 'records', row['id'], {'content': '备用钥匙改放在书房抽屉', 'aliases': ['后备钥匙']}, expected_version=shared['version'], request_id='correct')
    assert '书房' in service.search(users[0], '后备钥匙')['items'][0]['text']
    with pytest.raises(TaskError, match='version_conflict'):
        service.change(users[2], 'records', row['id'], {'content': '厨房'}, expected_version=shared['version'], request_id='race')
    service.change(users[0], 'records', row['id'], {'status': 'outdated'}, expected_version=fixed['version'], request_id='outdated')
    assert not service.search(users[0], '钥匙')['items']
    assert service.list(users[0], 'records', include_outdated=True)[0]['status'] == 'outdated'
    for i in range(2):
        service.save_record(users[0], request_id=f'event{i}', title='更换滤芯', content=f'第 {i + 1} 次更换滤芯', kind='event')
    assert len(service.list(users[0], 'records')) == 2


def test_idempotent_concurrent_document_save(library, tmp_path):
    service, users = library
    path = tmp_path / 'manual.txt'
    path.write_text('设备型号 ABC-900')
    def save(_):
        return service.save_document(users[0], path, request_id='same', title='说明书')['id']
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(save, range(4)))
    assert len(set(ids)) == 1
    assert len(service.list(users[0], 'documents')) == 1
    assert len(list(service.blobs.iterdir())) == 1


def test_partial_scan_and_failed_processing_are_truthful(library, tmp_path):
    from PIL import Image
    service, users = library
    image = tmp_path / 'blank.png'
    Image.new('RGB', (20, 20), 'white').save(image)
    row = service.save_document(users[0], image, request_id='image')
    assert row['status'] == 'failed' and row['warnings']
    assert not service.search(users[0], 'blank')['items']
    import pymupdf
    pdf = tmp_path / 'mixed.pdf'
    with pymupdf.open() as doc:
        doc.new_page().insert_text((72, 72), 'Model NUMBER-8810. Wash filter with clean water.')
        doc.new_page()
        doc.save(pdf)
    row = service.save_document(users[0], pdf, request_id='mixed')
    assert row['status'] == 'partial'
    match = service.search(users[0], 'NUMBER-8810')['items'][0]
    assert match['page'] == 1
    recognized = KnowledgeService(tmp_path / 'ocr', service.members, ocr=lambda _: '扫描件设备号 SCAN-001')
    assert recognized.save_document(users[0], image, request_id='ocr')['status'] == 'ready'


def test_old_library_answers_and_arguments_are_not_rehydrated():
    messages = [
        {'role': 'user', 'content': '钥匙在哪里'},
        {'role': 'assistant', 'tool_calls': [{'id': 'call', 'function': {'name': 'knowledge_search', 'arguments': '{"query":"秘密旧位置"}'}}]},
        {'role': 'tool', 'name': 'knowledge_search', 'content': '秘密旧位置'},
        {'role': 'assistant', 'content': '秘密旧位置'},
        {'role': 'user', 'content': '已经撤回共享，现在呢'},
    ]
    cleaned = fresh_knowledge_context(messages)
    assert '秘密旧位置' not in str(cleaned)
    assert '秘密旧位置' in str(messages)


def test_conflicting_facts_require_explicit_correction(library):
    service, users = library
    service.save_record(users[0], request_id='first', title='钥匙位置', content='玄关')
    with pytest.raises(TaskError, match='knowledge_record_conflict') as error:
        service.save_record(users[0], request_id='second', title='钥匙位置', content='书房')
    assert error.value.details['candidates'][0]['content'] == '玄关'
    assert len(service.list(users[0], 'records')) == 1


def test_revalidation_removes_current_run_evidence_after_revoke(library, tmp_path):
    import json
    service, users = library
    row = document(library, tmp_path)
    shared = service.change(users[0], 'documents', row['id'], {'visibility': 'household'}, expected_version=1, request_id='share')
    messages = [{'role': 'tool', 'name': 'knowledge_search', 'content': json.dumps({'status': 'success', 'output': service.search(users[1], '滤网')}, ensure_ascii=False)}]
    assert '清水' in str(service.current_tool_context(messages, users[1]))
    service.change(users[0], 'documents', row['id'], {'visibility': 'personal'}, expected_version=shared['version'], request_id='revoke')
    checked = service.current_tool_context(messages, users[1])
    assert '清水' not in str(checked) and 'knowledge_evidence_changed' in str(checked)
    assert '清水' not in service.finalize_answer(users[1], '清水冲洗即可', messages)


def test_final_answer_includes_verifiable_sources_when_model_omits_links(library, tmp_path):
    import json
    from utils.parser import InputParser
    service, users = library
    document(library, tmp_path)
    matches = service.search(users[0], '滤网')
    messages = [{'role': 'tool', 'name': 'knowledge_search', 'content': json.dumps({'status': 'success', 'output': matches}, ensure_ascii=False)}]
    answer = service.finalize_answer(users[0], '先断电，再清洗滤网。', messages)
    assert matches['items'][0]['source_url'] in answer
    assert service.finalize_answer(users[0], answer, messages) == answer
    assert not InputParser.needs_realtime_search('之前记住的备用钥匙放在哪里？请查最新记录。')
    assert InputParser.needs_realtime_search('查一下官网发布的最新说明书版本')


# 011 source regression set: 8 content, 4 paraphrase, 4 updates, 4 absence/ACL.
@pytest.mark.parametrize('query,expected', [
    ('清洗滤网', '清水'), ('排水管', '疏通'), ('型号', 'MODEL-A7'), ('保修', '两年'),
    ('电源', '断开'), ('安装', '水平'), ('除湿', '湿度'), ('遥控器', '电池'),
    ('冷气过滤网怎么清洁', '清水'), ('空调怎么清洗', '清水'), ('空调型号是什么', 'MODEL-A7'), ('空调保修多久', '两年'),
    ('备用钥匙放哪', '书房'), ('后备钥匙', '书房'), ('最近换滤芯', '2026-10-26'), ('我喜欢什么温度', '26 度'),
    ('不存在的门锁密码', None), ('竞争用户的账单', None), ('已过时旧信息标记', None), ('已删除的私密文件', None),
])
def test_twenty_source_regressions(library, tmp_path, query, expected):
    service, users = library
    contents = ['清洗滤网：用清水冲洗。', '排水管堵塞需疏通。', '型号 MODEL-A7。', '保修两年。',
                '先断开电源。', '水平安装。', '除湿模式降低湿度。', '遥控器需要更换电池。']
    for i, content in enumerate(contents):
        document(library, tmp_path, text=content, request_id=f'doc{i}', title=f'空调资料 {i}')
    row = service.save_record(users[0], request_id='key', title='备用钥匙', content='玄关', object_name='备用钥匙')
    service.change(users[0], 'records', row['id'], {'content': '备用钥匙放书房', 'aliases': ['后备钥匙']}, expected_version=1, request_id='fix')
    service.save_record(users[0], request_id='filter', title='最近换滤芯', content='2026-10-26 更换滤芯', kind='event')
    service.save_record(users[0], request_id='pref', title='喜欢的温度', content='我喜欢空调设定为 26 度', kind='preference')
    service.save_record(users[1], request_id='private', title='竞争用户的账单', content='不应泄露')
    stale = service.save_record(users[0], request_id='stale', title='已过时旧信息标记', content='不应召回')
    service.change(users[0], 'records', stale['id'], {'status': 'outdated'}, expected_version=1, request_id='retire')
    gone = document(library, tmp_path, text='不应召回', request_id='gone', title='已删除的私密文件')
    service.change(users[0], 'documents', gone['id'], {}, expected_version=1, request_id='del', delete=True)
    matches = service.search(users[0], query)['items']
    if expected:
        assert any(expected in match['text'] for match in matches), matches
    else:
        assert matches == []
