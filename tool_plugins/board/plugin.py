from dataclasses import replace
from agent_runtime.registry import ToolRegistry
from .tools import register_family_board_tools
from .hooks import Extension

class Plugin:
    def tools(self, context):
        services = context.services
        service = services['board']
        registry = ToolRegistry()
        register_family_board_tools(registry, service, context.get_user, context.get_execution_context, services["board_resolve_source"])
        return [replace(tool, replay_policy="revalidate") for tool in registry.list()]


    def extensions(self, context):
        return [Extension(context)]

def create_plugin():
    return Plugin()
