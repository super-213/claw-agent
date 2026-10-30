from agent_runtime.registry import ToolRegistry
from agent_runtime.family_activity_tools import register_activity_tools, ActivityExtension

class Plugin:
    def tools(self, context):
        registry = ToolRegistry()
        register_activity_tools(registry, context.services['family_activities'], context, 'relay')
        return registry.list()

    def extensions(self, context):
        return [ActivityExtension(context, 'relay')]

def create_plugin():
    return Plugin()
