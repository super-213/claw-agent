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

_NAME = re.compile(r'^[a-z][a-z0-9_]{0,63}$')


class PluginManager:
    def __init__(self, root, config_path=None):
        self.root = Path(root).resolve()
        self.config_path = Path(config_path).resolve() if config_path else None
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
                if folder.name == 'datetime':
                    raise RuntimeError('required_datetime_plugin_invalid') from None

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
        for key in ('runtimes', 'requires_services', 'requested_permissions'):
            if not isinstance(value.get(key), list) or any(not isinstance(item, str) for item in value[key]):
                raise ValueError('invalid_plugin_manifest')
        if not set(value['runtimes']) <= {'web', 'cli'}:
            raise ValueError('invalid_plugin_runtime')
        metadata = value.get('tool_metadata')
        if not isinstance(metadata, dict) or not metadata:
            raise ValueError('missing_tool_metadata')
        for name, item in metadata.items():
            if not _NAME.fullmatch(name) or name in {'tool_load', 'skill_load'} or not isinstance(item, dict):
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
        return setting

    def _enabled(self, plugin_id):
        return self._setting(plugin_id).get('enabled', plugin_id == 'datetime') is True

    def bind(self, registry: ToolRegistry, context: ToolBindingContext):
        for plugin_id, (folder, manifest, digest) in self.catalog.items():
            try:
                if not self._enabled(plugin_id) or context.runtime not in manifest['runtimes']:
                    continue
                setting = self._setting(plugin_id)
                permissions = set(manifest['requested_permissions'])
                grants = set(setting.get('permissions', []))
                if not permissions <= grants or not set(manifest['requires_services']) <= set(context.services):
                    raise ValueError('plugin_dependencies_or_grants_missing')
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
                module_name = package + '.' + Path(entry).stem
                spec = importlib.util.spec_from_file_location(module_name, folder / entry)
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                plugin = getattr(module, factory)()
                definitions = list(plugin.tools(context))
                if {d.name for d in definitions} != set(manifest['tool_metadata']):
                    raise ValueError('plugin_tools_manifest_mismatch')
                staged = ToolRegistry()
                for definition in definitions:
                    if not isinstance(definition, ToolDefinition) or not set(definition.capabilities) <= permissions:
                        raise ValueError('invalid_plugin_definition')
                    Draft202012Validator.check_schema(definition.input_schema)
                    if definition.input_schema.get('type') != 'object':
                        raise ValueError('plugin_schema_must_be_object')
                    metadata = manifest['tool_metadata'][definition.name]
                    source = {'id': plugin_id, 'version': manifest['version'], 'digest': digest,
                              'schema_digest': hashlib.sha256(json.dumps(definition.input_schema, sort_keys=True).encode()).hexdigest(),
                              'policy_digest': hashlib.sha256(json.dumps(setting, sort_keys=True).encode()).hexdigest()}
                    policy = self._policy(plugin_id, permissions, context)
                    staged.register(replace(definition, plugin_source=source,
                        plugin_authorize=policy, group=metadata['group'],
                        keywords=tuple(metadata.get('keywords', []))))
                for alias, target in manifest.get('aliases', {}).items():
                    if not isinstance(alias, str) or len(alias) > 200 or alias in {'tool_load', 'skill_load'}:
                        raise ValueError('invalid_plugin_alias')
                    staged.register_alias(alias, target)
                occupied = {d.name for d in registry.list()} | set(registry.aliases())
                if occupied & ({d.name for d in staged.list()} | set(staged.aliases())):
                    raise ValueError('plugin_tool_conflict')
                for definition in staged.list():
                    registry.register(definition)
                for alias, target in staged.aliases().items():
                    registry.register_alias(alias, target)
            except Exception:
                # Never include exception text: imports/service failures may contain credentials.
                self.errors[plugin_id] = 'plugin_bind_failed'
                if plugin_id == 'datetime':
                    raise RuntimeError('required_datetime_plugin_failed') from None
        return registry

    def _policy(self, plugin_id, permissions, context):
        def authorize(arguments):
            if not self._enabled(plugin_id):
                return False
            if not permissions <= set(self._setting(plugin_id).get('permissions', [])):
                return False
            return context.authorize(plugin_id, arguments) is True
        return authorize
