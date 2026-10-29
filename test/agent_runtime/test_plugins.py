"""Plugin contracts and native SDK wire-protocol integration; no network calls."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_runtime import RunStore, ToolCall, ToolRegistry
from agent_runtime.plugins import PluginManager, ToolBindingContext
from agent_runtime.tool_loading import ToolLoadingSession
from core.conversation import ConversationManager
from core.orchestrator import AgentOrchestrator
from services.llm_client import LLMClient
from services.conversation_store import ConversationStore
from services.session_state import conversation_messages_for_save
from skills.registry import SkillRegistry


def package(tmp_path, *, permissions=(), runtimes=('web', 'cli'), service=False):
    root = tmp_path / 'plugins'
    folder = root / 'counter'
    folder.mkdir(parents=True)
    manifest = {'id': 'counter', 'version': '1.0.0', 'api_version': 1,
        'entrypoint': 'plugin.py:create_plugin', 'runtimes': list(runtimes),
        'requires_services': ['counter'] if service else [],
        'requested_permissions': list(permissions),
        'tool_metadata': {'counter_read': {'group': 'numbers', 'keywords': ['数字', '计数']}},
        'aliases': {'counter.read': 'counter_read'}}
    (folder / 'plugin.json').write_text(json.dumps(manifest))
    (folder / 'helper.py').write_text('VALUE = 42\n')
    (folder / 'plugin.py').write_text('''from .helper import VALUE
from agent_runtime.models import ToolDefinition
class Plugin:
    def tools(self, context):
        return [ToolDefinition(name='counter_read', description='Read a number',
            input_schema={'type':'object','properties':{'n':{'type':'integer','minimum':1,'maximum':5}},
                          'required':['n'],'additionalProperties':False},
            handler=lambda args: {'value': VALUE, 'actor': context.get_user(), 'n':args['n']},
            idempotent=True)]
def create_plugin(): return Plugin()
''')
    config = tmp_path / 'plugins.toml'
    enable(config, permissions=permissions)
    return root, folder, config


def enable(config, enabled=True, permissions=()):
    config.write_text('[plugins.counter]\nenabled = ' + str(enabled).lower()
                      + '\npermissions = ' + json.dumps(list(permissions)) + '\n')


def bind(root, config, **context):
    registry = ToolRegistry()
    manager = PluginManager(root, config)
    manager.bind(registry, ToolBindingContext(runtime=context.pop('runtime', 'cli'), **context))
    return manager, registry


def test_default_datetime_and_dynamic_group(tmp_path):
    manager = PluginManager(Path(__file__).resolve().parents[2] / 'tool_plugins', tmp_path/'missing.toml')
    registry = manager.bind(ToolRegistry(), ToolBindingContext(runtime='cli'))
    assert registry.resolve_name('datetime.now') == 'datetime_now'
    result = asyncio.run(registry.invoke(ToolCall('time', 'datetime_now', {'timezone': 'UTC'})))
    assert result.success and result.output['timezone'] == 'UTC'
    assert registry.get('datetime_now').plugin_source['id'] == 'datetime'


def test_relative_imports_group_aliases_and_actor_isolation(tmp_path):
    root, folder, config = package(tmp_path)
    manager, first = bind(root, config, get_user=lambda: 'alice')
    second = manager.bind(ToolRegistry(), ToolBindingContext(runtime='web', get_user=lambda: 'bob'))
    for registry, actor in ((first, 'alice'), (second, 'bob')):
        loader = ToolLoadingSession(registry, lambda: None)
        assert 'numbers' in loader.schemas()[0]['function']['parameters']['properties']['group']['enum']
        assert 'numbers' in loader.catalog()
        assert loader.discover({'query': '计数'})['loaded'][0]['name'] == 'counter_read'
        result = asyncio.run(registry.invoke(ToolCall('read', 'counter.read', {'n': 2})))
        assert result.output == {'value': 42, 'actor': actor, 'n': 2}
    assert not manager.errors


def test_disabled_code_never_imported_and_grants_runtime_dependencies(tmp_path):
    root, folder, config = package(tmp_path, permissions=['network:public-read'], service=True)
    (folder/'plugin.py').write_text("raise AssertionError('must not import')")
    enable(config, False)
    manager, registry = bind(root, config)
    assert not registry.list() and not manager.errors
    enable(config)  # no grant and no service
    manager, registry = bind(root, config)
    assert not registry.list() and manager.errors == {'counter': 'plugin_dependencies_or_grants_missing'}
    root2 = tmp_path/'only_web'
    root2.mkdir()
    # Runtime filtering happens before code import.
    manifest = json.loads((folder/'plugin.json').read_text())
    manifest['runtimes'] = ['web']
    (folder/'plugin.json').write_text(json.dumps(manifest))
    manager, registry = bind(root, config)
    assert not registry.list() and not manager.errors


@pytest.mark.parametrize('arguments', [{'n':0}, {'n':6}, {'n':True}, {'n':2,'actor':'mallory'}, {}])
def test_full_schema_constraints(tmp_path, arguments):
    root, _, config = package(tmp_path)
    _, registry = bind(root, config)
    result = asyncio.run(registry.invoke(ToolCall('bad', 'counter_read', arguments)))
    assert not result.success and result.error


def test_revocation_and_host_denial_apply_even_when_approved(tmp_path):
    root, _, config = package(tmp_path, permissions=['network:public-read'])
    allowed = True
    _, registry = bind(root, config, authorize=lambda plugin, args: allowed)
    assert asyncio.run(registry.invoke(ToolCall('a', 'counter_read', {'n':2}))).success
    allowed = False
    assert asyncio.run(registry.invoke(ToolCall('b', 'counter_read', {'n':2}), approved=True)).error == 'plugin_access_denied'
    allowed = True
    enable(config, False)
    assert asyncio.run(registry.invoke(ToolCall('c', 'counter_read', {'n':2}), approved=True)).error == 'plugin_access_denied'
    enable(config, permissions=[])
    assert asyncio.run(registry.invoke(ToolCall('d', 'counter_read', {'n':2}))).error == 'plugin_access_denied'


def test_bad_manifest_escape_conflict_and_atomic_binding(tmp_path):
    root, folder, config = package(tmp_path)
    manifest = json.loads((folder/'plugin.json').read_text())
    manifest['entrypoint'] = '../outside.py:create_plugin'
    (folder/'plugin.json').write_text(json.dumps(manifest))
    manager, registry = bind(root, config)
    assert manager.errors == {'counter':'invalid_manifest'} and not registry.list()
    manifest['entrypoint'] = 'plugin.py:create_plugin'
    manifest['api_version'] = 2
    (folder/'plugin.json').write_text(json.dumps(manifest))
    assert bind(root, config)[0].errors
    manifest['api_version'] = 1
    manifest['aliases']['tool_load'] = 'counter_read'
    (folder/'plugin.json').write_text(json.dumps(manifest))
    manager, registry = bind(root, config)
    assert manager.errors and not registry.list()  # no partially installed tool
    manifest['aliases'].pop('tool_load')
    (folder/'plugin.json').write_text(json.dumps(manifest))
    manager, registry = bind(root, config)
    manager.bind(registry, ToolBindingContext(runtime='cli'))
    assert manager.errors and len(registry.list()) == 1


def test_catalog_code_change_requires_restart(tmp_path):
    root, folder, config = package(tmp_path)
    manager = PluginManager(root, config)
    (folder/'helper.py').write_text('VALUE = 10\n')
    registry = manager.bind(ToolRegistry(), ToolBindingContext(runtime='cli'))
    assert not registry.list() and manager.errors


@pytest.mark.parametrize('streaming', [False, True])
def test_native_sdk_protocol_and_persistence(tmp_path, streaming):
    root, folder, config = package(tmp_path)
    _, registry = bind(root, config)
    client = LLMClient(api_key='test', base_url='https://example.invalid/v1', model='explicit-model')
    requests = []
    async def create(**payload):
        assert payload['model'] == 'explicit-model'
        requests.append(deepcopy(payload))
        turn = len(requests)
        if turn == 1:
            assert {s['function']['name'] for s in payload['tools']} == {'tool_load'}
            tool, arguments = 'tool_load', {'group':'numbers'}
        elif turn == 2:
            assert {s['function']['name'] for s in payload['tools']} == {'tool_load','counter_read'}
            tool, arguments = 'counter_read', {'n':2}
        else:
            result = next(m for m in payload['messages'] if m.get('tool_call_id') == 'call2')
            assert json.loads(result['content'])['output']['value'] == 42
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='42', tool_calls=[]), finish_reason='stop')], usage=None, id='response')
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='', tool_calls=[SimpleNamespace(id=f'call{turn}', function=SimpleNamespace(name=tool, arguments=json.dumps(arguments)))]), finish_reason='tool_calls')], usage=None, id='response')
    client._async_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    # Drive the event-stream path with the same real SDK payload builder, without a network stream.
    async def stream(messages, schemas):
        yield {'type':'done', 'response':await client.achat_with_tools(messages, schemas)}
    client.astream_with_tools = stream
    conversation = ConversationManager('test')
    runs = RunStore(tmp_path/'runs')
    orchestrator = AgentOrchestrator(llm_client=client, conversation=conversation,
        skill_registry=SkillRegistry(str(tmp_path/'skills')), tool_registry=registry, run_store=runs)
    async def execute():
        if streaming:
            return [e async for e in orchestrator.process_user_input_stream_async('读取计数', session_id='session')]
        await orchestrator.process_user_input_async('读取计数', session_id='session')
    asyncio.run(execute())
    run = runs.load(orchestrator.run['id'])
    assert run['status'] == 'completed' and run['loaded_tools'] == ['counter_read']
    assert run['plugin_snapshot']['counter_read']['id'] == 'counter'
    assert conversation.get_messages()[-1]['content'] == '42'
    store = ConversationStore(tmp_path/'conversations')
    session = store.create_session("test")
    store.save_messages(session['id'], conversation_messages_for_save(conversation))
    assert store.load_session(session['id'])['messages'][-1]['content'] == '42'
    orchestrator.run = run
    # Both removal and an incompatible schema prevent old-run restoration.
    orchestrator.tool_registry = ToolRegistry()
    with pytest.raises(ValueError, match='plugin_snapshot_changed'):
        orchestrator._restore_skill_state()
    client._async_client = None
    client.close()


def test_cli_builder_discovers_enabled_package_without_registration_edits(tmp_path, monkeypatch):
    from agent_runtime.builtin_tools import build_tool_registry
    from services.executor import CommandExecutor
    root, folder, config = package(tmp_path)
    manager = PluginManager(root, config)
    monkeypatch.setattr(PluginManager, 'default', classmethod(lambda cls: manager))
    registry = build_tool_registry(project_root=tmp_path, generated_files_dir=tmp_path/'files',
                                   executor=CommandExecutor())
    assert registry.get('counter_read')  # This injected catalog intentionally contains only the test plugin.
    assert asyncio.run(registry.invoke(ToolCall('read', 'counter_read', {'n':1}))).success


def test_web_binding_uses_authenticated_actor_and_rechecks_revocation(tmp_path, monkeypatch):
    import web_app
    root, _, config = package(tmp_path)
    monkeypatch.setattr(web_app, 'plugin_manager', PluginManager(root, config))
    actor = {'id':'plugin-test-user', 'status':'active', 'role':'admin'}
    monkeypatch.setattr(web_app.user_store, 'get_user', lambda user_id: dict(actor))
    orchestrator = web_app._build_orchestrator(actor['id'])
    registry = orchestrator.tool_registry
    result = asyncio.run(registry.invoke(ToolCall('read', 'counter_read', {'n':1})))
    assert result.success and result.output['actor']['id'] == actor['id']
    actor['status'] = 'disabled'
    result = asyncio.run(registry.invoke(ToolCall('read2', 'counter_read', {'n':1}), approved=True))
    assert result.error == 'plugin_access_denied'


def test_pi_payload_includes_plugin_and_example_without_operator_config(tmp_path, monkeypatch):
    from deploy import build_pi_package as builder
    for name in (*builder.SINGLE_FILES, 'config/.env.example', 'web-react/dist/index.html',
                 'tool_plugins/datetime/plugin.py', 'tool_plugins/datetime/plugin.json',
                 'config/tool-plugins.toml'):
        path = tmp_path/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{}')
    monkeypatch.setattr(builder, 'ROOT', tmp_path)
    files = {str(path.relative_to(tmp_path)) for path in builder.package_files()}
    assert {'tool_plugins/datetime/plugin.py', 'tool_plugins/datetime/plugin.json',
            'config/tool-plugins.example.toml'} <= files
    assert 'config/tool-plugins.toml' not in files


def test_approval_resume_rechecks_plugin_authority(tmp_path):
    from agent_runtime import AgentModelResponse
    root, folder, config = package(tmp_path)
    code = (folder/'plugin.py').read_text().replace('idempotent=True)', 'idempotent=True, requires_confirmation=True)')
    (folder/'plugin.py').write_text(code)
    allowed = True
    _, registry = bind(root, config, authorize=lambda plugin, args: allowed)
    class Model:
        model = 'test'
        async def achat_with_tools(self, messages, schemas):
            if any(m.get('role') == 'tool' and m.get('name') == 'counter_read' for m in messages):
                return AgentModelResponse(content='操作未执行')
            return AgentModelResponse(tool_calls=[ToolCall('read', 'counter_read', {'n':1})])
    conversation = ConversationManager('test')
    runs = RunStore(tmp_path/'runs')
    def agent():
        return AgentOrchestrator(llm_client=Model(), conversation=conversation,
            skill_registry=SkillRegistry(str(tmp_path/'skills')), tool_registry=registry, run_store=runs)
    first = agent()
    asyncio.run(first.process_user_input_async('读取计数', session_id='approval'))
    assert first.run['status'] == 'waiting_approval'
    allowed = False
    async def resume():
        return [e async for e in agent().resume_after_approval_stream_async(
            first.run['id'], first.pending_approval_token, approved=True)]
    events = asyncio.run(resume())
    results = [e['tool_result'] for e in events if e.get('type') == 'tool_result']
    assert results and results[0]['error'] == 'plugin_access_denied'
    assert not any(r['status'] == 'success' for r in results)
