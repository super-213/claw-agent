"""Exercise shell helpers without starting or stopping the user's services."""
from pathlib import Path
import os
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def bash(code, env=None):
    return subprocess.run(['/bin/bash', '-c', code], env=env, text=True, capture_output=True)


def python_helpers():
    source = (ROOT / 'start.sh').read_text()
    return source[source.index('require_command()'):source.index('\nselect_python\n')]


def test_python_prefers_project_venv_with_spaces(tmp_path):
    executable = tmp_path / 'project with spaces/.venv/bin/python'
    executable.parent.mkdir(parents=True)
    executable.write_text('#!/bin/sh\nexit 0\n')
    executable.chmod(0o755)
    env = {**os.environ, 'PROJECT_DIR': str(executable.parents[2])}
    env.pop('PYTHON_BIN', None)
    result = bash(python_helpers() + '\nselect_python\nprintf "%s" "$PYTHON_BIN"', env)
    assert result.returncode == 0
    assert result.stdout == str(executable)


def test_python_falls_back_to_python3_and_honors_override(tmp_path):
    executable = tmp_path / 'python3'
    executable.write_text('#!/bin/sh\nexit 0\n')
    executable.chmod(0o755)
    env = {'PATH': str(tmp_path), 'PROJECT_DIR': str(tmp_path / 'absent')}
    result = bash(python_helpers() + '\nselect_python\nprintf "%s" "$PYTHON_BIN"', env)
    assert result.returncode == 0 and result.stdout == str(executable)
    env['PYTHON_BIN'] = '/missing/explicit-python'
    result = bash(python_helpers() + '\nselect_python', env)
    assert result.returncode != 0 and '/missing/explicit-python' in result.stderr


def test_status_uses_inferred_listener_for_api_health():
    source = (ROOT / 'status.sh').read_text()
    helpers = source[source.index('is_number()'):source.index('\nif [[ -f "$STATE_FILE"')]
    result = bash(helpers + '''
    pid_exists() { return 0; }
    pid_matches_project() { return 0; }
    listening_ports_for_pid() { printf 8000; }
    http_status() { printf 'checked %s' "$1"; }
    print_service API 123 '' /api/health
    ''')
    assert result.returncode == 0
    assert 'checked http://127.0.0.1:8000/api/health' in result.stdout
