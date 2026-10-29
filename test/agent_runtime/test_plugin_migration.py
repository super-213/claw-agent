"""P2–P4 authority, history, extension and source-integration regression."""
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

from agent_runtime import AgentModelResponse, RunStore, ToolCall, ToolDefinition, ToolRegistry
from agent_runtime.builtin_tools import build_tool_registry
from agent_runtime.card_presenter import CardPresenter
from agent_runtime.mcp_adapter import MCPAdapter
from agent_runtime.plugins import PluginManager, ToolBindingContext
from core.conversation import ConversationManager
from core.orchestrator import AgentOrchestrator
from services.executor import CommandExecutor
from skills.registry import SkillRegistry

ROOT = Path(__file__).resolve().parents[2]


def manager(tmp_path, disabled=()):
    config = tmp_path/'plugins.toml'
    config.write_text(''.join(f'[plugins.{name}]\nenabled = false\n' for name in disabled))
    return PluginManager(ROOT/'tool_plugins', config)


def test_foundation_sources_and_shell_is_excluded_from_web(tmp_path):
    for family_mode in [False, True]:
        registry = build_tool_registry(project_root=tmp_path, generated_files_dir=tmp_path/'files',
            executor=CommandExecutor(), family_mode=family_mode,
            skill_registry=SkillRegistry(str(ROOT/'skills')))
        for name, plugin in [('datetime_now','datetime'),('file_read','files'),('file_write','files'),
                             ('http_request','public_http'),('skill_load','skills')]:
            assert registry.get(name).plugin_source['id'] == plugin
        assert bool(registry.get('shell_execute')) is not family_mode
        assert registry.resolve_name('file.read') == 'file_read'


def test_disabled_domain_cannot_reuse_historical_evidence_or_memory(tmp_path):
    registry = manager(tmp_path, ['knowledge']).bind(ToolRegistry(), ToolBindingContext(runtime='web'))
    assert registry.get('knowledge_search') is None
    messages = [{'role':'system','content':'policy'}, {'role':'user','content':'old'},
        {'role':'assistant','content':'secret-derived', 'tool_calls':[{
            'id':'old','type':'function','function':{'name':'knowledge_search','arguments':'{"query":"secret"}'}}]},
        {'role':'tool','name':'knowledge_search','tool_call_id':'old','content':'secret-private'},
        {'role':'assistant','content':'secret-summary'}, {'role':'user','content':'again'}]
    assert registry.hooks.any('preserve_history', messages)
    assert registry.hooks.any('avoid_memory', messages)
    filtered = registry.hooks.transform('prepare_history', messages)
    assert 'secret' not in json.dumps(filtered)
    assert 'secret' in json.dumps(messages)  # persistent UI history is not rewritten
    assert filtered[3]['tool_call_id'] == 'old'


def test_extension_filters_compose_and_first_denial_cannot_be_overwritten():
    registry = ToolRegistry()
    class First:
        def validate_answer(self, content, messages, retries): return content, 'denied'
        def filter_context(self, messages): return [*messages, 'first']
    class Second:
        def validate_answer(self, *args): raise AssertionError('must not override refusal')
        def filter_context(self, messages): return [*messages, 'second']
    registry.hooks.add(First()); registry.hooks.add(Second())
    assert registry.hooks.transform('filter_context', []) == ['first','second']
    assert registry.hooks.validate_answer('answer', [], 0) == ('answer','denied')


def test_plugin_owned_card_declaration_has_no_central_name_mapping():
    definition = ToolDefinition('poll_create','test',{'type':'object'},lambda args: None,
        card_kind='poll', card_resource_types=('poll',))
    from agent_runtime.models import ToolResult
    result = ToolResult('id','poll_create','success',output={'ui_blocks':[{
        'type':'interactive_card','schema_version':1,'kind':'poll','mode':'saved',
        'card_id':'c','resource':{'type':'poll','id':'p'},'html':'untrusted markup'}]})
    blocks = CardPresenter().present(result, definition)
    assert len(blocks) == 1 and 'html' not in blocks[0]


def test_mcp_source_native_loop_approval_and_persisted_provider_revision(tmp_path):
    cfg = {'id':'home','enabled':True,'command':sys.executable,
        'args':[str(ROOT/'scripts/mcp_status_server.py')], 'user_ids':['alice'],
        'tools':['service_status'], 'require_confirmation':True}
    user = {'id':'alice','status':'active'}
    class Members:
        def actor(self, actor): return 'A'
    adapter = MCPAdapter([cfg],tmp_path/'audit.json')
    config = tmp_path/'plugins.toml'
    config.write_text('')
    plugin_manager = PluginManager(ROOT/'tool_plugins',config)
    registry = plugin_manager.bind(ToolRegistry(), ToolBindingContext(runtime='web',
        services={'mcp':adapter,'family_members':Members()}, get_user=lambda:user))
    tool = registry.get('mcp_home_service_status')
    assert tool and tool.plugin_source['id'] == 'mcp' and tool.plugin_source['provider_digest']
    assert tool.replay_policy == 'revalidate'
    requests=[]
    class Model:
        model='local-test'
        async def achat_with_tools(self, messages, schemas):
            names={s['function']['name'] for s in schemas}; requests.append(names)
            if 'mcp_home_service_status' not in names:
                return AgentModelResponse(tool_calls=[ToolCall('load','tool_load',{'group':'external'})])
            if not any(m.get('name')=='mcp_home_service_status' for m in messages):
                return AgentModelResponse(tool_calls=[ToolCall('read','mcp_home_service_status',{})])
            return AgentModelResponse(content='service checked')
    conversation=ConversationManager('test');runs=RunStore(tmp_path/'runs')
    agent=AgentOrchestrator(llm_client=Model(),conversation=conversation,
        skill_registry=SkillRegistry(str(tmp_path/'skills')),tool_registry=registry,run_store=runs)
    asyncio.run(agent.process_user_input_async('check',session_id='s'))
    assert requests[0] == {'tool_load'} and agent.run['status']=='waiting_approval'
    async def resume():
        return [event async for event in agent.resume_after_approval_stream_async(
            agent.run['id'],agent.pending_approval_token,approved=True)]
    events=asyncio.run(resume())
    result=next(e['tool_result'] for e in events if e.get('type')=='tool_result')
    assert result['output']['trust']=='untrusted_external_data'
    persisted=runs.load(agent.run['id'])
    assert persisted['status']=='completed'
    assert persisted['plugin_snapshot']['mcp_home_service_status']['provider_digest']
    config.write_text('[plugins.mcp]\nenabled = false\n')
    assert asyncio.run(registry.invoke(ToolCall('again','mcp_home_service_status',{}),approved=True)).error=='plugin_access_denied'


def test_metadata_diagnostics_do_not_import_plugins_or_discover_mcp(tmp_path, monkeypatch):
    from agent_runtime.mcp_adapter import StdioClient
    remote=Mock(side_effect=AssertionError('must not contact MCP'))
    monkeypatch.setattr(StdioClient,'exchange',remote)
    rows=manager(tmp_path).describe('web')
    assert next(row for row in rows if row['id']=='mcp')['dynamic_tools']
    assert next(row for row in rows if row['id']=='shell')['state']=='runtime_excluded'
    remote.assert_not_called()


def test_all_builtin_manifests_are_valid(tmp_path):
    catalog=manager(tmp_path)
    assert not catalog.errors
    assert {'files','public_http','skills','shell','home_assistant','family_tasks','board','knowledge','mcp'} <= set(catalog.catalog)


def test_file_revalidation_denies_cached_bytes_after_grant_revocation(tmp_path):
    from agent_runtime.plugins.access import FileToolAccess
    root=tmp_path/'files';root.mkdir();(root/'shared.txt').write_text('private-text')
    permitted=True
    def authorize(user, path):
        if not permitted: raise PermissionError('file_not_found')
    registry=ToolRegistry()
    file_access=FileToolAccess(tmp_path,root,user_id='alice',get_user=lambda:{'id':'alice'},
                               authorize_generated=authorize)
    registry=manager(tmp_path).bind(registry,ToolBindingContext(runtime='web',services={'files':file_access}))
    tool=registry.get('file_read')
    assert tool.replay_policy=='revalidate'
    call=ToolCall('read','file_read',{'path':'/generated/shared.txt'})
    assert asyncio.run(registry.invoke(call)).output['content']=='private-text'
    permitted=False
    assert asyncio.run(registry.invoke(call)).error=='file_not_found'


def test_service_scope_does_not_expose_undeclared_host_dependencies(tmp_path):
    from test_plugins import package, enable
    root,folder,config=package(tmp_path)
    code=(folder/'plugin.py').read_text().replace('def tools(self, context):',
        "def tools(self, context):\n        assert not context.services")
    (folder/'plugin.py').write_text(code)
    registry=PluginManager(root,config).bind(ToolRegistry(),ToolBindingContext(runtime='cli',services={'credential_store':object()}))
    assert registry.get('counter_read')


def test_legacy_datetime_snapshot_remains_compatible(tmp_path):
    import hashlib
    registry=manager(tmp_path).bind(ToolRegistry(),ToolBindingContext(runtime='cli'))
    source=registry.get('datetime_now').plugin_source
    assert source['policy_digest']==hashlib.sha256(b'{}').hexdigest()


def test_external_plugin_service_dependencies_require_host_grants(tmp_path):
    from test_plugins import package
    root,folder,config=package(tmp_path, service=True)
    plugin_manager=PluginManager(root,config)
    context=ToolBindingContext(runtime='cli',services={'counter':object()})
    assert not plugin_manager.bind(ToolRegistry(),context).list()
    config.write_text(config.read_text()+'services = ["counter"]\n')
    registry=PluginManager(root,config).bind(ToolRegistry(),context)
    assert registry.get('counter_read')
    config.write_text(config.read_text().replace('services = ["counter"]', 'services = []'))
    assert asyncio.run(registry.invoke(ToolCall('read','counter_read',{'n':1}),approved=True)).error=='plugin_access_denied'


def test_admin_manifest_endpoint_is_read_only(tmp_path, monkeypatch):
    import web_app
    monkeypatch.setattr(web_app,'plugin_manager',manager(tmp_path))
    monkeypatch.setitem(web_app.app.config,'TESTING',True)
    with web_app.app.test_client() as client:
        response=client.get('/api/runtime/plugins')
    assert response.status_code==200
    data=response.get_json()
    assert data['validation']=='manifest-only'
    assert {'mcp','files','knowledge'} <= {p['id'] for p in data['plugins']}
    assert 'credentials' not in json.dumps(data)


def test_compatibility_presenter_reads_plugin_owned_card_declarations():
    from agent_runtime.card_presenter import builtin_card_presenter
    from agent_runtime.models import ToolResult
    result=ToolResult('call','family_task_get','success',output={'ui_blocks':[{
        'type':'interactive_card','schema_version':1,'kind':'task','mode':'saved',
        'card_id':'c','resource':{'type':'family_task','id':'task'}}]})
    assert builtin_card_presenter().present(result)[0]['resource']['id']=='task'


def test_nested_entrypoint_relative_imports_and_reserved_bridge(tmp_path):
    from test_plugins import package
    root,folder,config=package(tmp_path)
    nested=folder/'impl';nested.mkdir()
    for name in ['plugin.py','helper.py']:
        (folder/name).rename(nested/name)
    path=folder/'plugin.json';manifest=json.loads(path.read_text())
    manifest['entrypoint']='impl/plugin.py:create_plugin';path.write_text(json.dumps(manifest))
    registry=PluginManager(root,config).bind(ToolRegistry(),ToolBindingContext(runtime='cli'))
    assert asyncio.run(registry.invoke(ToolCall('read','counter_read',{'n':1}))).output['value']==42
    manifest['tool_metadata']['skill_load']={'group':'other'};path.write_text(json.dumps(manifest))
    assert PluginManager(root,config).errors=={'counter':'invalid_manifest'}


def test_new_domain_resource_event_needs_no_task_shaped_result(tmp_path):
    registry=ToolRegistry()
    registry.register(ToolDefinition('poll_create','create poll',{'type':'object'},lambda args:{'poll_id':'p'}))
    class Extension:
        def resource_events(self, result):
            return [{'type':'resource_changed','resource_type':'poll','resource_ids':[result.output['poll_id']]}]
    registry.hooks.add(Extension())
    class Model:
        model='test'
        async def achat_with_tools(self, messages, schemas):
            if any(m.get('name')=='poll_create' for m in messages):return AgentModelResponse(content='done')
            return AgentModelResponse(tool_calls=[ToolCall('poll','poll_create',{})])
    runtime=AgentOrchestrator(llm_client=Model(),conversation=ConversationManager('test'),
        skill_registry=SkillRegistry(str(tmp_path/'skills')),tool_registry=registry,run_store=RunStore(tmp_path/'runs'))
    async def run():
        return [e async for e in runtime.process_user_input_stream_async('poll',session_id='s')]
    events=asyncio.run(run())
    assert any(e.get('resource_type')=='poll' for e in events)
    assert runtime.run['status']=='completed'


def test_unverified_stream_is_buffered_and_correction_is_bounded(tmp_path):
    registry=ToolRegistry()
    registry.register(ToolDefinition('available','test',{'type':'object'},lambda args:None))
    class Extension:
        def defer_output(self):return True
        def validate_answer(self, content, messages, retries):return content,'not verified'
    registry.hooks.add(Extension())
    class Model:
        model='test'
        count=0
        async def achat_with_tools(self, messages, schemas):return AgentModelResponse(content='unverified')
        async def astream_with_tools(self, messages, schemas):
            self.count+=1
            yield {'type':'content_delta','delta':'unverified'}
            yield {'type':'done','response':AgentModelResponse(content='unverified')}
    model=Model()
    runtime=AgentOrchestrator(llm_client=model,conversation=ConversationManager('test'),
        skill_registry=SkillRegistry(str(tmp_path/'skills')),tool_registry=registry,run_store=RunStore(tmp_path/'runs'))
    async def run():
        return [e async for e in runtime.process_user_input_stream_async('check',session_id='s')]
    events=asyncio.run(run())
    assert model.count==3 and runtime.run['status']=='failed'
    assert runtime.run['error']=='answer_verification_failed'
    assert not any(e.get('type')=='model_delta' for e in events)
    assert not any(m.get('role')=='assistant' for m in runtime.conversation.get_messages())


def test_host_loader_history_does_not_disable_ordinary_context_compression(tmp_path):
    registry=manager(tmp_path).bind(ToolRegistry(),ToolBindingContext(runtime='cli'))
    messages=[{'role':'tool','name':'tool_load','content':'loaded datetime_now'},
              {'role':'tool','name':'datetime_now','content':'current time'}]
    assert not registry.hooks.any('preserve_history',messages)


def test_domain_extension_order_preserves_task_then_board_validation(tmp_path):
    from types import SimpleNamespace
    # Factories can be inspected without executing any domain operation.
    runtime=SimpleNamespace(run=None,family_task_context={})
    from tool_plugins.family_tasks.hooks import Extension as Tasks
    from tool_plugins.board.hooks import Extension as Board
    context=ToolBindingContext(runtime='web',services={'runtime':lambda:runtime})
    registry=ToolRegistry()
    registry.hooks.add(Board(context),priority=200)
    registry.hooks.add(Tasks(context),priority=100)
    assert [type(e).__module__ for e in registry.hooks.extensions][-2:]==[
        'tool_plugins.family_tasks.hooks','tool_plugins.board.hooks']
