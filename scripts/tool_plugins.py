#!/usr/bin/env python3
"""Read-only plugin catalog diagnostics; no plugin imports, tool calls or MCP traffic."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_runtime.plugins import PluginManager


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['list', 'validate'])
    parser.add_argument('--runtime', choices=['cli', 'web'])
    parser.add_argument('--config')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    manager = PluginManager(root / 'tool_plugins', args.config or os.getenv('TOOL_PLUGINS_CONFIG') or root / 'config/tool-plugins.toml')
    print(json.dumps({'validation': 'manifest-only', 'plugins': manager.describe(args.runtime)},
                     ensure_ascii=False, indent=2))
    return int(bool(manager.errors)) if args.action == 'validate' else 0


if __name__ == '__main__':
    raise SystemExit(main())
