from agent_runtime.models import ToolDefinition
from agent_runtime.registry import ToolRegistry

class Plugin:
    def tools(self, context):
        registry = ToolRegistry()
        services = context.services
        browser_handler = services.get('browser_handler')
        app_handler = services.get('app_handler')
        if browser_handler is not None:
            registry.register(ToolDefinition(
                name="browser_open",
                description="Open a public URL in an attached browser capability.",
                input_schema={
                    "type": "object",
                    "properties": {"url": {"type": "string", "minLength": 1, "maxLength": 4096}},
                    "required": ["url"],
                    "additionalProperties": False,
                },
                handler=browser_handler,
                risk_level="medium",
                requires_confirmation=True,
                capabilities=("browser:open", "network:external"),
            ))

        if app_handler is not None:
            registry.register(ToolDefinition(
                name="app_control",
                description="Control an explicitly attached application capability.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "app": {"type": "string", "minLength": 1, "maxLength": 200},
                        "action": {"type": "string", "enum": ["open", "focus", "close"]},
                    },
                    "required": ["app", "action"],
                    "additionalProperties": False,
                },
                handler=app_handler,
                risk_level="critical",
                requires_confirmation=True,
                capabilities=("system:application-control",),
            ))

        return registry.list()

def create_plugin():
    return Plugin()
