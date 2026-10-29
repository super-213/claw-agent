from services.home_assistant_service import HomeAssistantService, POWER_DOMAINS
from typing import Any
from agent_runtime.models import ToolDefinition
from agent_runtime.registry import ToolRegistry
from agent_runtime import builtin_tools as io

class Plugin:
    def tools(self, context):
        registry = ToolRegistry()
        services = context.services
        home_assistant_service = services['home_assistant']
        if (
            home_assistant_service is not None
            and home_assistant_service.configured
            and home_assistant_service.rules
        ):
            _register_home_assistant(registry, home_assistant_service)

        return registry.list()

def create_plugin():
    return Plugin()

def _register_home_assistant(registry: ToolRegistry, service: HomeAssistantService) -> None:
    descriptions = {row["name"]: row for row in service.tools_schema()}
    allowed_ids = sorted(service.rules)
    power_ids = [
        entity_id
        for entity_id in allowed_ids
        if entity_id.split(".", 1)[0] in POWER_DOMAINS
    ]
    name_map = {
        "home_assistant_list_devices": "home_assistant.list_devices",
        "home_assistant_get_state": "home_assistant.get_state",
        "home_assistant_turn_on": "home_assistant.turn_on",
        "home_assistant_turn_off": "home_assistant.turn_off",
    }
    for public_name, service_name in name_map.items():
        schema = descriptions[service_name]
        if service_name.endswith(("turn_on", "turn_off")) and not power_ids:
            continue
        input_schema = dict(schema["parameters"])
        input_schema["properties"] = dict(input_schema.get("properties") or {})
        if "entity_id" in input_schema["properties"]:
            entity_ids = power_ids if service_name.endswith(("turn_on", "turn_off")) else allowed_ids
            input_schema["properties"]["entity_id"] = {
                "type": "string",
                "enum": entity_ids,
            }
        description = schema["description"]
        if service_name.endswith("get_state"):
            description += (
                " Use this only for the listed smart-home entities, never for a "
                "general public weather or web query."
            )
        registry.register(ToolDefinition(
            name=public_name,
            description=description,
            input_schema=input_schema,
            handler=lambda args, name=service_name: _call_home_assistant(service, name, args),
            risk_level="high" if service_name.endswith(("turn_on", "turn_off")) else "low",
            requires_confirmation=service_name.endswith(("turn_on", "turn_off")),
            timeout=max(2, service.request_timeout + 2),
            replay_policy="revalidate" if service_name.endswith(("list_devices", "get_state")) else "cache",
            idempotent=service_name.endswith(("list_devices", "get_state")),
            max_retries=1,
        ))


def _call_home_assistant(
    service: HomeAssistantService,
    name: str,
    args: dict[str, Any],
) -> Any:
    if name == "home_assistant.turn_on":
        return service.set_power(str(args.get("entity_id") or ""), True, confirmed=True)
    if name == "home_assistant.turn_off":
        return service.set_power(str(args.get("entity_id") or ""), False, confirmed=True)
    return service.call_tool(name, args)
