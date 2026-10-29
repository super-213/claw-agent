"""Install inert skill packages into the host-configured registry, never run scripts."""
from __future__ import annotations

import base64
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import time
from urllib.parse import quote, unquote, urlsplit

from .registry import SkillRegistry


class SkillInstaller:
    MAX_FILES = 128
    MAX_BYTES = 8 * 1024 * 1024

    def __init__(self, registry: SkillRegistry, fetch):
        self.registry, self.fetch = registry, fetch

    def _get(self, url):
        response = self.fetch({'url': url, 'max_chars': 2 * 1024 * 1024})
        if response.get('truncated') or response.get('status') != 200:
            raise ValueError('skill_download_incomplete')
        return response

    def _json(self, url):
        return json.loads(self._get(url)['body'])

    def install(self, args):
        deadline = time.monotonic() + 120
        url = str(args['url'])
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError('skill_requires_public_https_url')
        parts = [unquote(p) for p in parsed.path.strip('/').split('/')]
        files = {}
        if parsed.hostname in {'github.com', 'raw.githubusercontent.com'}:
            if len(parts) < 2 or (parsed.hostname == 'raw.githubusercontent.com' and len(parts) < 4) or any(p in {'', '.', '..'} or '/' in p or '\\' in p for p in parts):
                raise ValueError('invalid_github_skill_url')
            owner, repo = parts[:2]
            repo = repo.removesuffix('.git')
            api = f'https://api.github.com/repos/{quote(owner, safe="")}/{quote(repo, safe="")}'
            if parsed.hostname == 'raw.githubusercontent.com':
                ref, path = parts[2], parts[3:]
            elif len(parts) == 2:
                ref, path = self._json(api)['default_branch'], []
            elif len(parts) >= 4 and parts[2] in {'tree', 'blob'}:
                ref, path = parts[3], parts[4:]
            else:
                raise ValueError('use_github_repository_directory_or_skill_file_url')
            if path and path[-1] == 'SKILL.md':
                path = path[:-1]
            prefix = '/'.join(path)
            name = args.get('name') or (path[-1] if path else repo)
            # Pin every file to one immutable commit even if the branch moves while downloading.
            revision = self._json(f'{api}/commits/{quote(ref, safe="")}')['sha']
            tree = self._json(f'{api}/git/trees/{quote(revision, safe="")}?recursive=1')
            if tree.get('truncated'):
                raise ValueError('github_tree_truncated')
            entries = []
            for entry in tree.get('tree', []):
                remote = entry['path']
                if prefix and not remote.startswith(prefix + '/'):
                    continue
                relative = remote[len(prefix) + 1:] if prefix else remote
                if entry['type'] == 'tree':
                    continue
                if entry.get('mode') not in {'100644', '100755'} or entry['type'] != 'blob':
                    raise ValueError('skill_symlinks_and_submodules_not_allowed')
                self._safe_path(relative)
                entries.append((relative, entry))
            if not entries or len(entries) > self.MAX_FILES or sum(e.get('size', 0) for _, e in entries) > self.MAX_BYTES:
                raise ValueError('skill_package_size_limit')
            if not any(path == 'SKILL.md' for path, _ in entries):
                raise ValueError('skill_directory_requires_SKILL_md')
            for relative, entry in entries:
                if time.monotonic() > deadline:
                    raise TimeoutError('skill_download_deadline_exceeded')
                blob = self._json(f'{api}/git/blobs/{quote(entry["sha"], safe="")}')
                if blob.get('encoding') != 'base64':
                    raise ValueError('unsupported_github_blob_encoding')
                files[relative] = base64.b64decode(re.sub(r'\s', '', blob['content']), validate=True)
        else:
            if not parsed.path.endswith('/SKILL.md'):
                raise ValueError('use_github_directory_or_direct_SKILL_md_url')
            name = args.get('name') or parts[-2]
            response = self._get(url)
            if 'html' in response.get('content_type', '').lower() or response['body'].lstrip().lower().startswith(('<!doctype html', '<html')):
                raise ValueError('skill_url_returned_html')
            files['SKILL.md'] = response['body'].encode('utf-8')
        name = self.registry._validate_skill_name(str(name))
        if sum(map(len, files.values())) > self.MAX_BYTES:
            raise ValueError('skill_package_size_limit')
        instructions = files.get('SKILL.md', b'').decode('utf-8')
        if not instructions.strip():
            raise ValueError('empty_skill_instructions')
        root = self.registry.skills_dir.resolve()
        root.mkdir(parents=True, exist_ok=True)
        destination = root / name
        with self.registry._lock:
            if destination.exists() or destination.is_symlink():
                raise FileExistsError(f'skill_already_exists:{name}')
            stage = Path(tempfile.mkdtemp(prefix='.skill-install-', dir=root))
            try:
                for relative, data in files.items():
                    target = stage / self._safe_path(relative)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                    if target.read_bytes() != data:
                        raise RuntimeError('skill_file_verification_failed')
                manifest = self.registry._load_manifest(stage, name)
                stage.rename(destination)
                self.registry.reload()
                skill = self.registry.get(name)
                if skill is None or skill.load_context() != instructions:
                    shutil.rmtree(destination)
                    self.registry.reload()
                    raise RuntimeError('skill_registration_failed')
            finally:
                if stage.exists():
                    shutil.rmtree(stage)
        return {'name': name, 'status': 'installed', 'registered': True,
                'version': manifest.version, 'files': sorted(files), 'source_url': url,
                'required_tools': list(manifest.required_tools),
                'dependencies_installed': False}

    @staticmethod
    def _safe_path(value):
        path = PurePosixPath(value)
        if not value or path.is_absolute() or any(p in {'', '.', '..'} for p in value.split('/')) or '\\' in value or '\x00' in value:
            raise ValueError('unsafe_skill_package_path')
        return path
