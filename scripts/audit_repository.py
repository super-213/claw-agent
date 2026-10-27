#!/usr/bin/env python3
"""Report tracked/history risk metadata. Never print source text or secret values."""
import collections
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


def check_index():
    paths = git('ls-files', '-z').decode().split('\0')
    blocked = [path for path in paths if not path.endswith('.env.example') and re.search(
        r'(^|/)(node_modules/|\.data/|\.webui_secret_key|\.env(?:\.[^/]+)?$|mcp\.toml$)|\.(?:pem|p12|key)$', path)]
    if blocked:
        print('Blocked sensitive/generated paths in Git index: ' + ', '.join(blocked[:10]), file=sys.stderr)
        return 1
    print('Git index security check passed.')
    return 0


def git(*args):
    return subprocess.check_output(['git', *args])


def audit():
    tracked = git('ls-files', '-z').decode().split('\0')
    objects = git('rev-list', '--objects', '--all').decode().splitlines()
    sensitive = re.compile(r'(^|/)(\.data/|\.webui_secret_key|\.env$|auth_sessions\.json$|users\.json$)')
    risks = []
    candidates = []
    # Distinct historical blobs, rather than directory presence or commit counts.
    for entry in objects:
        oid, _, path = entry.partition(' ')
        if not sensitive.search(path):
            continue
        if git('cat-file', '-t', oid).strip() != b'blob':
            continue
        body = git('cat-file', 'blob', oid)
        risks.append({'path': path, 'object': oid, 'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()})
        if '.env' in path:
            for key, value in re.findall(rb'^([A-Z_]*(?:KEY|TOKEN|PASSWORD|SECRET)[A-Z_]*)=(.+)$', body, re.M):
                value = value.strip().strip(b'\'"')
                if len(value) >= 12 and not re.search(rb'(your_|example|placeholder)', value, re.I):
                    candidates.append({'path': path, 'variable': key.decode(), 'sha256': hashlib.sha256(value).hexdigest()})
    return {'tracked_dependencies': sum('/node_modules/' in '/' + p for p in tracked),
            'tracked_sensitive_paths': [p for p in tracked if sensitive.search(p)],
            'historical_sensitive_blobs': risks, 'credential_candidates': candidates,
            'historical_path_counts': dict(collections.Counter(r['path'].split('/')[0] for r in risks)),
            'note': 'Candidates are not proof of current validity. Provider revocation and remote-history cleanup require operator verification.'}


if __name__ == '__main__':
    if '--check-index' in sys.argv:
        raise SystemExit(check_index())
    print(json.dumps(audit(), indent=2, ensure_ascii=False))
