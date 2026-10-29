from agent_runtime.models import ToolDefinition
from agent_runtime.registry import ToolRegistry

class Plugin:
    def tools(self, context):
        registry = ToolRegistry()
        services = context.services
        skill_registry = services['skills']
        if skill_registry is not None:
            names = [row["name"] for row in skill_registry.catalog(auto_only=True)]
            if names:
                registry.register(ToolDefinition(
                    name="skill_load",
                    description=(
                        "Load the full instructions for one capability package after selecting it "
                        "from the compact skill catalog."
                    ),
                    input_schema={
                        "type": "object",
                        "properties": {"name": {"type": "string", "enum": names}},
                        "required": ["name"],
                        "additionalProperties": False,
                    },
                    handler=lambda args: skill_registry.load_for_runtime(
                        str(args["name"]),
                        available_tools=(
                            {tool.name for tool in services['registry'].list()} | set(services['registry'].aliases())
                        ),
                        automatic=True,
                    ),
                    idempotent=True,
                    max_retries=1,
                    capabilities=("skill:read",),
                ))

        return registry.list()

def create_plugin():
    return Plugin()
