"""Host-owned per-run dependencies; never populated from model arguments."""
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class ToolBindingContext:
    runtime: str
    services: Mapping[str, Any] = field(default_factory=dict)
    get_user: Callable[[], Any] = lambda: None
    get_execution_context: Callable[[], dict] = lambda: {}
    authorize: Callable[[str, dict], bool] = lambda plugin_id, args: True

    def __post_init__(self):
        if self.runtime not in {'web', 'cli'}:
            raise ValueError('invalid_plugin_runtime')
        object.__setattr__(self, 'services', MappingProxyType(dict(self.services)))
