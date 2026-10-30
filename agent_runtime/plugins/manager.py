"""Startup catalog, atomic per-package binding and execution-time policy checks."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tomllib
import types

from jsonschema import Draft202012Validator

from agent_runtime.models import ToolDefinition
from agent_runtime.registry import ToolRegistry
from .contracts import ToolBindingContext

# Host-owned defaults apply only to reviewed packages shipped in this repository.
BUNDLED = {'datetime': (), 'files': (), 'public_http': ('network:public-read',),
           'shell': (), 'skills': ('skill:read', 'skill:install', 'network:public-read'), 'attached': ('browser:open', 'network:external', 'system:application-control'),
           'home_assistant': (), 'family_tasks': (), 'board': (), 'family_polls': (), 'family_relays': (), 'knowledge': (), 'mcp': ('mcp', 'read_only')}
_NAME = re.compile(r'^[a-z][a-z0-9_]{0,63}$')


class PluginManager:
    def __init__(self, root, config_path=None):
        self.root = Path(root).resolve()
        self.config_path = Path(config_path).resolve() if config_path else None
        self.bundled = self.root == Path(__file__).resolve().parents[2] / "tool_plugins"
        self.catalog = {}
        self.errors = {}
        self.config = self._config()
        for folder in sorted(self.root.iterdir()) if self.root.exists() else []:
            if not folder.is_dir() or not (folder / 'plugin.json').exists():
                continue
            try:
                manifest = self._manifest(folder)
                self.catalog[manifest['id']] = (folder.resolve(), manifest, self._digest(folder))
            except Exception:
                self.errors[folder.name] = 'invalid_manifest'

        if self.bundled:
            for plugin_id in ('datetime', 'files', 'public_http', 'skills'):
                if self._enabled(plugin_id) and plugin_id not in self.catalog:
                    raise RuntimeError(f'required_plugin_manifest_invalid:{plugin_id}')

    @classmethod
    def default(cls):
        project = Path(__file__).resolve().parents[2]
        return cls(project / 'tool_plugins', os.getenv('TOOL_PLUGINS_CONFIG') or project / 'config/tool-plugins.toml')

    def _config(self):
        if not self.config_path or not self.config_path.exists():
            return {'plugins': {}}
        with self.config_path.open('rb') as handle:
            config = tomllib.load(handle)
        if not isinstance(config.get('plugins', {}), dict):
            raise ValueError('invalid_plugin_config')
        return config

    def _manifest(self, folder):
        if folder.is_symlink() or not folder.resolve().is_relative_to(self.root):
            raise ValueError('plugin_path_escape')
        path = folder / 'plugin.json'
        if not path.resolve().is_relative_to(folder.resolve()):
            raise ValueError('plugin_path_escape')
        value = json.loads(path.read_text())
        if not isinstance(value, dict) or value.get('id') != folder.name or not _NAME.fullmatch(folder.name):
            raise ValueError('invalid_plugin_id')
        if type(value.get('api_version')) is not int or value['api_version'] != 1:
            raise ValueError('incompatible_plugin_api')
        if not isinstance(value.get('version'), str) or not value['version']:
            raise ValueError('invalid_plugin_version')
        for key in ('runtimes', 'requires_services', 'requested_permissions', 'optional_services'):
            if not isinstance(value.get(key, []), list) or any(not isinstance(item, str) for item in value.get(key, [])):
                raise ValueError('invalid_plugin_manifest')
        if any(key not in value for key in ('runtimes', 'requires_services', 'requested_permissions')):
            raise ValueError('invalid_plugin_manifest')
        if type(value.get('extension_order', 0)) is not int:
            raise ValueError('invalid_extension_order')
        card = value.get('cards')
        if card is not None and (not isinstance(card, dict) or not _NAME.fullmatch(card.get('kind', ''))
                or not isinstance(card.get('resource_types'), list)
                or any(not isinstance(item, str) or not _NAME.fullmatch(item) for item in card['resource_types'])):
            raise ValueError('invalid_plugin_card_declaration')
        if not set(value['runtimes']) <= {'web', 'cli'}:
            raise ValueError('invalid_plugin_runtime')
        metadata = value.get('tool_metadata')
        if not isinstance(metadata, dict) or (not metadata and not (self.bundled and value.get('dynamic_tools'))):
            raise ValueError('missing_tool_metadata')
        for name, item in metadata.items():
            if not _NAME.fullmatch(name) or (name == 'tool_load' or (name == 'skill_load' and not (self.bundled and folder.name == 'skills'))) or not isinstance(item, dict):
                raise ValueError('invalid_tool_metadata')
            if not _NAME.fullmatch(item.get('group', '')):
                raise ValueError('invalid_tool_group')
            if not isinstance(item.get('keywords', []), list) or any(not isinstance(s, str) for s in item.get('keywords', [])):
                raise ValueError('invalid_tool_keywords')
        entry, function = value.get('entrypoint', '').split(':')
        target = (folder / entry).resolve()
        if not target.is_relative_to(folder.resolve()) or not target.is_file() or target.suffix != '.py' or not function.isidentifier():
            raise ValueError('invalid_plugin_entrypoint')
        # Also prevent relative imports and resource reads escaping via symlinks.
        if any(p.is_symlink() for p in folder.rglob('*')):
            raise ValueError('plugin_symlinks_disabled')
        return value

    @staticmethod
    def _digest(folder):
        digest = hashlib.sha256()
        for path in sorted(folder.rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix in {'.py', '.json'}:
                digest.update(str(path.relative_to(folder)).encode())
                digest.update(path.read_bytes())
        return digest.hexdigest()

    def _setting(self, plugin_id):
        # Only the migrated, reviewed time plugin is enabled out of the box.
        setting = self._config().get('plugins', {}).get(plugin_id, {})
        if not isinstance(setting, dict):
            raise ValueError('invalid_plugin_setting')
        defaults = {'permissions': list(BUNDLED[plugin_id])} if self.bundled and BUNDLED.get(plugin_id) else {}
        return {**defaults, **setting}

    def _enabled(self, plugin_id):
        return self._setting(plugin_id).get('enabled', (self.bundled and plugin_id in BUNDLED)) is True

    def bind(self, registry: ToolRegistry, context: ToolBindingContext, *, bundled_only=False):
        for plugin_id, (folder, manifest, digest) in self.catalog.items():
            try:
                if (bundled_only and plugin_id not in BUNDLED) or not self._enabled(plugin_id) or context.runtime not in manifest['runtimes']:
                    continue
                setting = self._setting(plugin_id)
                permissions = set(manifest['requested_permissions'])
                grants = set(setting.get('permissions', []))
                requested_services = set(manifest['requires_services']) | set(manifest.get('optional_services', []))
                approved_services = set(setting.get('services', requested_services if self.bundled and plugin_id in BUNDLED else []))
                if (not permissions <= grants or not set(manifest['requires_services']) <= set(context.services)
                        or not requested_services <= approved_services):
                    self.errors[plugin_id] = 'plugin_dependencies_or_grants_missing'
                    continue
                # Recheck before importing code. Per-binding instance: no actor shared across requests.
                current = self._manifest(folder)
                if current != manifest or self._digest(folder) != digest:
                    raise ValueError('plugin_manifest_changed_restart_required')
                package = '_claw_plugin_' + plugin_id + '_' + digest
                if package not in sys.modules:
                    module = types.ModuleType(package)
                    module.__path__ = [str(folder)]
                    sys.modules[package] = module
                entry, factory = manifest['entrypoint'].split(':')
                parts = Path(entry).with_suffix('').parts
                if any(not part.isidentifier() for part in parts):
                    raise ValueError('invalid_plugin_entrypoint')
                for depth in range(1, len(parts)):
                    namespace = package + '.' + '.'.join(parts[:depth])
                    if namespace not in sys.modules:
                        subpackage = types.ModuleType(namespace)
                        subpackage.__path__ = [str(folder.joinpath(*parts[:depth]))]
                        sys.modules[namespace] = subpackage
                module_name = package + '.' + '.'.join(parts)
                spec = importlib.util.spec_from_file_location(module_name, folder / entry)
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                plugin = getattr(module, factory)()
                service_names = set(manifest['requires_services']) | set(manifest.get('optional_services', []))
                binding = replace(context, services={name: context.services[name]
                    for name in service_names if name in context.services})
                definitions = list(plugin.tools(binding))
                declared, actual = set(manifest['tool_metadata']), {d.name for d in definitions}
                if manifest.get('dynamic_tools') and self.bundled:
                    if any(not name.startswith('mcp_') for name in actual):
                        raise ValueError('invalid_dynamic_tool_name')
                elif actual != declared and not (manifest.get('optional_tools') and actual <= declared):
                    raise ValueError('plugin_tools_manifest_mismatch')
                staged = ToolRegistry()
                for definition in definitions:
                    if not isinstance(definition, ToolDefinition) or not set(definition.capabilities) <= permissions:
                        raise ValueError('invalid_plugin_definition')
                    Draft202012Validator.check_schema(definition.input_schema)
                    if definition.input_schema.get('type') != 'object':
                        raise ValueError('plugin_schema_must_be_object')
                    metadata = manifest['tool_metadata'].get(definition.name, {'group': 'external'})
                    source = {'id': plugin_id, 'version': manifest['version'], 'digest': digest,
                              'schema_digest': hashlib.sha256(json.dumps(definition.input_schema, sort_keys=True).encode()).hexdigest(),
                              'policy_digest': hashlib.sha256(json.dumps(setting, sort_keys=True).encode()).hexdigest(),
                              **({"provider_digest": definition.plugin_source['provider_digest']} if 'provider_digest' in definition.plugin_source else {})}
                    policy = self._policy(plugin_id, permissions, context, requested_services)
                    staged.register(replace(definition, plugin_source=source,
                        plugin_authorize=policy, group=metadata['group'],
                        card_kind=manifest.get('cards', {}).get('kind', definition.card_kind),
                        card_resource_types=tuple(manifest.get('cards', {}).get('resource_types', definition.card_resource_types)),
                        keywords=tuple(metadata.get('keywords', []))))
                for alias, target in manifest.get('aliases', {}).items():
                    if target not in actual:
                        continue
                    if not isinstance(alias, str) or len(alias) > 200 or alias in {'tool_load', 'skill_load'}:
                        raise ValueError('invalid_plugin_alias')
                    staged.register_alias(alias, target)
                occupied = {d.name for d in registry.list()} | set(registry.aliases())
                if occupied & ({d.name for d in staged.list()} | set(staged.aliases())):
                    raise ValueError('plugin_tool_conflict')
                extensions = list(plugin.extensions(binding)) if hasattr(plugin, 'extensions') else []
                for definition in staged.list():
                    registry.register(definition)
                for alias, target in staged.aliases().items():
                    registry.register_alias(alias, target)
                for extension in extensions:
                    registry.hooks.add(extension, priority=manifest.get("extension_order", 0))
                self.errors.pop(plugin_id, None)
            except Exception:
                # Never include exception text: imports/service failures may contain credentials.
                self.errors[plugin_id] = 'plugin_bind_failed'
                if self.bundled and plugin_id in {'datetime', 'files', 'public_http', 'skills'}:
                    raise RuntimeError(f'required_plugin_failed:{plugin_id}') from None
        return registry

    def describe(self, runtime=None):
        """Manifest-only diagnostics: never import code or contact remote MCP servers."""
        rows = []
        for plugin_id, (_, manifest, digest) in self.catalog.items():
            enabled = self._enabled(plugin_id)
            rows.append({'id': plugin_id, 'version': manifest['version'], 'digest': digest,
                'enabled': enabled, 'runtimes': manifest['runtimes'],
                'state': 'disabled' if not enabled else 'runtime_excluded'
                         if runtime and runtime not in manifest['runtimes'] else 'discovered',
                'requires_services': manifest['requires_services'],
                'tools': sorted(manifest['tool_metadata']), 'dynamic_tools': bool(manifest.get('dynamic_tools')),
                'last_bind_error': self.errors.get(plugin_id)})
        for plugin_id, error in self.errors.items():
            if plugin_id not in self.catalog:
                rows.append({'id': plugin_id, 'state': 'invalid', 'error': error})
        return rows

    def _policy(self, plugin_id, permissions, context, requested_services=()):
        def authorize(arguments):
            if not self._enabled(plugin_id):
                return False
            setting = self._setting(plugin_id)
            if not permissions <= set(setting.get('permissions', [])):
                return False
            defaults = requested_services if self.bundled and plugin_id in BUNDLED else []
            if not set(requested_services) <= set(setting.get('services', defaults)):
                return False
            return context.authorize(plugin_id, arguments) is True
        return authorize
