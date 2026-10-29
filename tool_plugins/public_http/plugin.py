from agent_runtime.models import ToolDefinition
from agent_runtime.registry import ToolRegistry

class Plugin:
    def tools(self, context):
        registry = ToolRegistry()
        services = context.services

        registry.register(ToolDefinition(
            name="http_request",
            description="Perform a public HTTP GET or HEAD request and return a bounded text response.",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "minLength": 1, "maxLength": 4096},
                    "method": {"type": "string", "enum": ["GET", "HEAD"]},
                    "headers": {"type": "object", "additionalProperties": {"type": "string"}},
                    "max_chars": {"type": "integer"},
                },
                "required": ["url"],
                "additionalProperties": False,
            },
            handler=lambda args: services['public_http'](args),
            timeout=20,
            replay_policy="revalidate",
            idempotent=True,
            max_retries=2,
            capabilities=("network:public-read",),
            allowed_domains=tuple(services.get('allowed_http_domains', ())),
        ))

        return registry.list()

def create_plugin():
    return Plugin()
