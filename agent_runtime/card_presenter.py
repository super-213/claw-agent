"""Versioned, allowlisted references shared by chat and future workbench surfaces."""
from copy import deepcopy
import hashlib


def card_reference(kind, resource_type, resource_id, instance_id=None, context=None, *, mode='saved'):
    context = context or {}
    resource = {'type': resource_type, 'id': resource_id}
    if instance_id:
        resource['instance_id'] = instance_id
    origin = context.get('request_id') or context.get('run_id') or context.get('session_id') or 'resource'
    identity = '\0'.join([origin, kind, resource_type, resource_id, instance_id or ''])
    return {'type': 'interactive_card', 'schema_version': 1, 'kind': kind, 'mode': mode,
            'card_id': 'card_' + hashlib.sha256(identity.encode()).hexdigest()[:24], 'resource': resource,
            'source': {k: context[k] for k in ('run_id', 'tool_call_id') if context.get(k)}}


class CardPresenter:
    def __init__(self):
        self._tools = {}

    def register(self, kind, resource_types, tool_names):
        for tool in tool_names:
            if tool in self._tools:
                raise ValueError('card_tool_already_registered')
            self._tools[tool] = (kind, set(resource_types))

    def present(self, result, definition=None):
        registration = ((definition.card_kind, set(definition.card_resource_types))
                        if definition and definition.card_kind else self._tools.get(result.name))
        if not registration:
            return []
        candidates = result.metadata.get('ui_blocks') or (result.output.get('ui_blocks', []) if isinstance(result.output, dict) else [])
        valid = {}
        for block in candidates:
            if not isinstance(block, dict):
                continue
            resource = block.get('resource')
            if not isinstance(resource, dict):
                continue
            if (block.get('type') != 'interactive_card' or block.get('schema_version') != 1
                    or block.get('kind') != registration[0] or resource.get('type') not in registration[1]
                    or not isinstance(resource.get('id'), str) or not isinstance(block.get('card_id'), str)
                    or block.get('mode') not in {'saved', 'draft'}
                    or (not result.success and block.get('mode') != 'draft')):
                continue
            # Store reference fields only; no markup, arbitrary actions or URLs.
            clean = {k: deepcopy(block[k]) for k in ('type', 'schema_version', 'kind', 'mode', 'card_id', 'resource', 'source') if k in block}
            clean['resource'] = {k: resource[k] for k in ('type', 'id', 'instance_id') if isinstance(resource.get(k), str)}
            source = clean.get('source') if isinstance(clean.get('source'), dict) else {}
            clean['source'] = {k: value for k, value in source.items()
                               if k in {'run_id', 'tool_call_id'} and isinstance(value, str)}
            clean['source']['tool_call_id'] = result.call_id
            valid[clean['card_id']] = clean
        return list(valid.values())


def builtin_card_presenter():
    """Compatibility facade reading plugin-owned declarations without importing code."""
    from .plugins import PluginManager
    presenter = CardPresenter()
    for _, manifest, _ in PluginManager.default().catalog.values():
        card = manifest.get('cards')
        if card:
            presenter.register(card['kind'], card['resource_types'], manifest['tool_metadata'])
    return presenter
