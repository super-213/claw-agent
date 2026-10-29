"""Link installation, native tool loading/approval, registration and explicit calls."""
import asyncio
import base64
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from agent_runtime import AgentModelResponse, RunStore, ToolCall, ToolRegistry
from agent_runtime.plugins import PluginManager, ToolBindingContext
from core.conversation import ConversationManager
from core.orchestrator import AgentOrchestrator
from skills.installer import SkillInstaller
from skills.registry import SkillRegistry
from utils.parser import InputParser

ROOT = Path(__file__).resolve().parents[2]
URL = 'https://github.com/example/repo/tree/main/skills/demo'


def github_fetch(files=None):
    files = files or {'SKILL.md': b'# Demo\nUse native tools.', 'scripts/helper.py': b'print("not executed")', 'references/info.txt': b'context'}
    def fetch(args):
        url = args['url']
        if '/commits/' in url:
            data = {'sha': 'pinned'}
        elif '/git/trees/pinned?' in url:
            data = {'tree': [{'path': 'skills/demo/' + path, 'type': 'blob', 'mode': '100644', 'sha': str(i), 'size': len(content)} for i, (path, content) in enumerate(files.items())]}
        else:
            data = {'encoding': 'base64', 'content': base64.b64encode(list(files.values())[int(url.rsplit('/', 1)[1])]).decode()}
        return {'status': 200, 'body': json.dumps(data), 'truncated': False}
    return Mock(side_effect=fetch)


def bind(tmp_path, skills, installer, actor=None, runtime='cli'):
    registry = ToolRegistry()
    manager = PluginManager(ROOT / 'tool_plugins', tmp_path / 'plugins.toml')
    manager.bind(registry, ToolBindingContext(runtime=runtime, services={
        'skills': skills, 'skill_installer': installer, 'registry': registry}, get_user=lambda: actor))
    return registry


def test_installs_configured_directory_and_retains_resources(tmp_path):
    skills = SkillRegistry(str(tmp_path / 'configured-skills'))
    fetch = github_fetch()
    result = SkillInstaller(skills, fetch).install({'url': URL})
    assert result['registered'] and result['status'] == 'installed'
    assert skills.list_skills() == ['demo']
    assert skills.get('demo').load_context().startswith('# Demo')
    assert (skills.skills_dir / 'demo/scripts/helper.py').read_text() == 'print("not executed")'
    assert all('/git/trees/pinned?' in c.args[0]['url'] or '/git/blobs/' in c.args[0]['url'] or '/commits/' in c.args[0]['url'] for c in fetch.call_args_list)
    with pytest.raises(FileExistsError):
        SkillInstaller(skills, fetch).install({'url': URL})
    assert not list(skills.skills_dir.glob('.skill-install-*'))


@pytest.mark.parametrize('bad', ['../escape', '/absolute', 'scripts/../../escape', 'scripts\\escape'])
def test_rejects_package_traversal(tmp_path, bad):
    skills = SkillRegistry(str(tmp_path / 'skills'))
    with pytest.raises(ValueError):
        SkillInstaller(skills, github_fetch({'SKILL.md': b'good', bad: b'bad'})).install({'url': URL})
    assert not skills.list_skills()


def test_rejects_bad_manifest_and_cleans_staging(tmp_path):
    skills = SkillRegistry(str(tmp_path / 'skills'))
    with pytest.raises(ValueError):
        SkillInstaller(skills, github_fetch({'SKILL.md': b'good', 'manifest.json': b'{bad'})).install({'url': URL})
    assert list(skills.skills_dir.iterdir()) == []


def test_incomplete_response_and_html_are_not_installed(tmp_path):
    skills = SkillRegistry(str(tmp_path / 'skills'))
    for response in [dict(status=200, body='partial', truncated=True), dict(status=200, body='<html>page</html>', content_type='text/html')]:
        with pytest.raises(ValueError):
            SkillInstaller(skills, lambda args: response).install({'url': 'https://example.com/demo/SKILL.md'})
    assert not skills.list_skills()


def test_preserves_public_network_policy(tmp_path, monkeypatch):
    from agent_runtime.plugins.assembly import foundation_services
    from agent_runtime import builtin_tools
    monkeypatch.setattr(builtin_tools.socket, 'getaddrinfo', lambda *args: [(None, None, None, None, ('127.0.0.1', 443))])
    services = foundation_services(registry=ToolRegistry(), project_root=tmp_path,
        generated_files_dir=tmp_path/'files', executor=None, skill_registry=SkillRegistry(str(tmp_path/'skills')))
    with pytest.raises(PermissionError, match='private_network'):
        services['skill_installer'].install({'url':'https://localhost/demo/SKILL.md'})
    assert not list((tmp_path/'skills').glob('*'))


def test_web_install_requires_admin_and_rechecks_role(tmp_path):
    skills = SkillRegistry(str(tmp_path/'skills'))
    installer = SkillInstaller(skills, github_fetch())
    assert bind(tmp_path, skills, installer, {'role':'member','status':'active'}, 'web').get('skill_install') is None
    actor = {'role':'admin','status':'active'}
    registry = bind(tmp_path, skills, installer, actor, 'web')
    actor['role'] = 'member'
    result = asyncio.run(registry.invoke(ToolCall('install','skill_install',{'url':URL}), approved=True))
    assert not result.success and not skills.list_skills()


@pytest.mark.parametrize('use_sdk', [False, True])
@pytest.mark.parametrize('confirmation', [False, True])
def test_native_install_approval_resume_and_new_skill_load(tmp_path, use_sdk, confirmation):
    skills = SkillRegistry(str(tmp_path/'skills'))
    fetch = github_fetch()
    registry = bind(tmp_path, skills, SkillInstaller(skills, fetch))
    if confirmation:
        from dataclasses import replace
        registry._tools['skill_install'] = replace(registry.get('skill_install'), requires_confirmation=True)
    requests = []
    class Model:
        model = 'test-model'
        async def achat_with_tools(self, messages, schemas):
            names = {s['function']['name'] for s in schemas}
            requests.append(names)
            if 'skill_install' not in names:
                return AgentModelResponse(tool_calls=[ToolCall('load', 'tool_load', {'names':['skill_install']})])
            if not any(m.get('name') == 'skill_install' for m in messages):
                return AgentModelResponse(tool_calls=[ToolCall('install', 'skill_install', {'url':URL})])
            if not any(m.get('name') == 'skill_load' for m in messages):
                return AgentModelResponse(tool_calls=[ToolCall('activate', 'skill_load', {'name':'demo'})])
            assert any('Use native tools.' in str(m.get('content')) for m in messages)
            return AgentModelResponse(content='installed and loaded')
    runs = RunStore(tmp_path/'runs')
    model = Model()
    sdk_payloads = []
    if use_sdk:
        from types import SimpleNamespace as N
        from services.llm_client import LLMClient
        driver = model
        async def create(**kwargs):
            sdk_payloads.append(kwargs)
            response = await driver.achat_with_tools(kwargs['messages'], kwargs['tools'])
            calls = [N(index=i, id=c.id, type='function', function=N(name=c.name, arguments=json.dumps(c.arguments))) for i, c in enumerate(response.tool_calls)]
            message = N(content=response.content, tool_calls=calls)
            if kwargs.get('stream'):
                async def chunks():
                    yield N(choices=[N(delta=message, finish_reason='tool_calls' if calls else 'stop')])
                return chunks()
            return N(choices=[N(message=message, finish_reason='tool_calls' if calls else 'stop')])
        model = LLMClient(api_key='test-only', base_url='https://example.invalid/v1', model='explicit-model', max_retries=0)
        model._async_client = N(chat=N(completions=N(create=create)))
    agent = AgentOrchestrator(llm_client=model, conversation=ConversationManager('test'),
        skill_registry=skills, tool_registry=registry, run_store=runs)
    asyncio.run(agent.process_user_input_async('请安装这个技能 '+URL, session_id='s'))
    assert requests[0] == {'tool_load','skill_load'}
    if confirmation:
        assert agent.run['status'] == 'waiting_approval'
        fetch.assert_not_called()
        async def resume():
            return [e async for e in agent.resume_after_approval_stream_async(agent.run['id'], agent.pending_approval_token, approved=True)]
        asyncio.run(resume())
    else:
        assert agent.run['status'] == 'completed'
    persisted = runs.load(agent.run['id'])
    assert persisted['status'] == 'completed'
    assert persisted['active_skill'] == 'demo'
    results = [s['tool_result'] for s in persisted['steps'] if 'tool_result' in s]
    assert any(r.get('output', {}).get('registered') is True for r in results)
    assert skills.has_skill('demo')
    if use_sdk:
        assert all(p['model'] == 'explicit-model' for p in sdk_payloads)
        assert {t['function']['name'] for t in sdk_payloads[0]['tools']} == {'tool_load', 'skill_load'}
        assert any(m.get('role') == 'tool' and m.get('name') == 'skill_install' for m in sdk_payloads[-1]['messages'])
        model.client.close()


@pytest.mark.parametrize(('text','expected'), [('$ demo do work',('demo','do work')), ('$ demo',('demo','')), ('$demo hi',(None,'$demo hi')), ('price $ demo',(None,'price $ demo')), ('`$ demo`',(None,'`$ demo`'))])
def test_dollar_grammar(text, expected):
    assert InputParser.parse_user_input(text) == expected


def test_explicit_only_skill_can_be_called_without_auto_catalog(tmp_path):
    skills = SkillRegistry(str(tmp_path/'skills'))
    SkillInstaller(skills, github_fetch({'SKILL.md':b'explicit instructions',
        'manifest.json':json.dumps({'name':'demo','allow_auto':False}).encode()})).install({'url':URL})
    assert skills.catalog(auto_only=True) == []
    with pytest.raises(PermissionError):
        skills.load_for_runtime('demo', automatic=True)
    agent = AgentOrchestrator(llm_client=object(), conversation=ConversationManager('test'), skill_registry=skills)
    accepted, events = agent._prepare_user_input('$ demo do work', emit_events=True)
    assert accepted and any(e.get('stage') == 'skill_loaded' for e in events)
    messages = agent.conversation.get_messages()
    assert messages[-1]['content'] == 'do work'
    assert any('explicit instructions' in m['content'] for m in messages)


def test_external_frontmatter_supplies_auto_discovery_description_without_grants(tmp_path):
    skills = SkillRegistry(str(tmp_path/'skills'))
    SkillInstaller(skills, github_fetch({'SKILL.md': b'---\nname: foreign-name\ndescription: >\n  Generate useful reports\n  from documents.\nallowed_tools: [shell_execute]\n---\n# Instructions'})).install({'url':URL})
    row = skills.catalog(auto_only=True)[0]
    assert row['name'] == 'demo' and 'Generate useful reports' in row['summary']
    assert skills.get('demo').allowed_tools() is None


@pytest.mark.parametrize('mode', ['120000', '160000'])
def test_symlink_and_submodule_entries_are_rejected(tmp_path, mode):
    def fetch(args):
        data = {'sha':'pinned'} if '/commits/' in args['url'] else {'tree':[
            {'path':'skills/demo/SKILL.md','type':'blob','mode':mode,'sha':'bad'}]}
        return {'status':200, 'body':json.dumps(data)}
    skills = SkillRegistry(str(tmp_path/'skills'))
    with pytest.raises(ValueError, match='symlinks_and_submodules'):
        SkillInstaller(skills, fetch).install({'url':URL})
    assert not skills.list_skills()
