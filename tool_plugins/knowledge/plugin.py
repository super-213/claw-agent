from dataclasses import replace
from agent_runtime.registry import ToolRegistry
from .tools import register_knowledge_tools
from .hooks import Extension

class Plugin:
    def tools(self, context):
        services = context.services
        service = services['knowledge']
        registry = ToolRegistry()
        register_knowledge_tools(registry, service, context.get_user, context.get_execution_context, services["knowledge_resolve_file"])
        return [replace(tool, replay_policy="revalidate", card_kind='',
                        card_resource_types=()) for tool in registry.list()]

    def extensions(self, context):
        return [Extension(context)]

def create_plugin():
    return Plugin()
