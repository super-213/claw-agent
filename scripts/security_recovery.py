#!/usr/bin/env python3
"""Offline operator recovery. Stop Claw first; never logs hashes or passwords."""
import argparse
import getpass
import json
from pathlib import Path
import secrets
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from config import ConfigManager
from services.user_store import UserStore
from services.auth_service import AuthSessionStore
from services.passkeys import PasskeyService


def exposed_hashes():
    found = set()
    for entry in subprocess.check_output(['git', 'rev-list', '--objects', '--all'], cwd=ROOT).decode().splitlines():
        oid, _, path = entry.partition(' ')
        if path != '.data/users.json':
            continue
        if subprocess.check_output(['git', 'cat-file', '-t', oid], cwd=ROOT).strip() != b'blob':
            continue
        try:
            document = json.loads(subprocess.check_output(['git', 'cat-file', 'blob', oid], cwd=ROOT))
            found.update(row['password_hash'] for row in document.get('users', []) if row.get('password_hash'))
        except (ValueError, TypeError, KeyError):
            continue
    return found


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Interactively reset affected passwords and revoke sessions/passkeys; server must be stopped')
    parser.add_argument('--rotate-legacy-key', action='store_true')
    args = parser.parse_args()
    config = ConfigManager()
    path = Path(config['user_file'])
    if not path.is_absolute():
        path = ROOT / path
    users = UserStore(path)
    exposed = exposed_hashes()
    affected = [row for row in users.list_users(include_password=True) if row.get('password_hash') in exposed]
    print(f'Active/local accounts with historically exposed password hashes: {len(affected)}')
    if args.rotate_legacy_key:
        key = ROOT / '.webui_secret_key'
        key.write_text(secrets.token_urlsafe(48))
        key.chmod(0o600)
        print('Legacy key rotated. Current FastAPI authentication uses opaque session tokens.')
    if args.apply:
        replacements = []
        for user in affected:
            password = getpass.getpass(f"New password for {user['username']}: ")
            if len(password) < 12 or password != getpass.getpass('Confirm new password: '):
                raise SystemExit('Password mismatch or shorter than 12 characters; nothing changed.')
            if users.check_password(password, user['password_hash']):
                raise SystemExit('New password must differ; nothing changed.')
            replacements.append((user['id'], password))
        sessions = AuthSessionStore(path=path.with_name('auth_sessions.json'))
        passkeys = PasskeyService(path.with_name('passkeys.json'))
        for identity, password in replacements:
            users.reset_password(identity, password)
            sessions.revoke_user(identity)
            passkeys.revoke_user(identity)
        print(f'Reset {len(replacements)} accounts. Restart Claw to discard all in-memory sessions.')
    elif affected:
        print('Stop the server, then run this script with --apply to set NEW passwords and revoke sessions/passkeys.')
