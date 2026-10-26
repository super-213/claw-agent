"""Run 010 touch-browser checks against temporary users, storage and a model stub.

Requires Playwright (Python) and installed Google Chrome. No external model calls.
Example: python3 scripts/validate_home_workbench.py
"""
from pathlib import Path
import os
import runpy
import signal
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

root = Path(__file__).resolve().parents[1]

def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def wait_ready(url):
    for _ in range(100):
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(.1)
    raise RuntimeError(f'Preview failed to start: {url}')


api_port, web_port = free_port(), free_port()
env = {**os.environ, 'HOME010_API_PORT': str(api_port), 'VITE_API_TARGET': f'http://127.0.0.1:{api_port}'}
output = root / '.data/validation/home-workbench'
output.mkdir(parents=True, exist_ok=True)
os.environ['HOME010_SCREENSHOTS'] = str(output)
os.environ['HOME010_WEB_ORIGIN'] = f'http://127.0.0.1:{web_port}'
processes = []
try:
    processes.append(subprocess.Popen([sys.executable, str(root / 'test/browser/home_workbench_server.py')], cwd=root, env=env, stdout=subprocess.DEVNULL, start_new_session=True))
    wait_ready(f'http://127.0.0.1:{api_port}/api/auth/usernames')
    processes.append(subprocess.Popen(['npm', '--prefix', str(root / 'web-react'), 'run', 'dev', '--', '--host', '127.0.0.1', '--port', str(web_port), '--strictPort'], cwd=root, env=env, stdout=subprocess.DEVNULL, start_new_session=True))
    wait_ready(os.environ['HOME010_WEB_ORIGIN'])
    runpy.run_path(str(root / 'test/browser/home_workbench_checks.py'), run_name='__main__')
    runpy.run_path(str(root / 'test/browser/family_navigation_checks.py'), run_name='__main__')
    print(f'010 browser validation passed. Screenshots: {output}')
finally:
    for process in reversed(processes):
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    for process in reversed(processes):
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
