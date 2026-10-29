from dataclasses import replace
from agent_runtime.registry import ToolRegistry
from .tools import register_family_task_tools
from .hooks import Extension

class Plugin:
    def tools(self, context):
        services = context.services
        service = services['family_tasks']
        registry = ToolRegistry()
        register_family_task_tools(registry, service, context.get_user, context.get_execution_context)
        return [replace(tool, replay_policy="revalidate") for tool in registry.list()]


    def extensions(self, context):
        return [Extension(context)]

def create_plugin():
    return Plugin()
