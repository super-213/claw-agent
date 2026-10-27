#!/usr/bin/env python3
"""Minimal read-only MCP stdio server for local family service status (no secrets)."""
import json
import sys
import urllib.request

SCHEMA = {'type': 'object', 'properties': {}, 'additionalProperties': False}
for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request:
        continue
    method = request['method']
    if method == 'initialize':
        result = {'protocolVersion': '2025-11-25', 'capabilities': {'tools': {}},
                  'serverInfo': {'name': 'claw-local-status', 'version': '1.0'}}
    elif method == 'tools/list':
        result = {'tools': [{'name': 'service_status', 'description': 'Read local Claw service health',
                            'inputSchema': SCHEMA, 'annotations': {'readOnlyHint': True}}]}
    elif method == 'tools/call' and request['params']['name'] == 'service_status':
        try:
            with urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2) as response:
                healthy = response.status == 200
        except OSError:
            healthy = False
        result = {'content': [{'type': 'text', 'text': 'Claw API reachable' if healthy else 'Claw API unavailable'}],
                  'structuredContent': {'service': 'claw', 'healthy': healthy}}
    else:
        print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'error': {'code': -32601, 'message': 'Unknown method'}}), flush=True)
        continue
    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)
