"""Validate generated configs and real Nginx routing without touching launchd."""
import importlib.util
import json
from pathlib import Path
import plistlib
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('mac_config', ROOT / 'deploy/mac-config.py')
mac = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mac)


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class MacDeployTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mac deploy & ')
        self.addCleanup(self.temp.cleanup)
        self.app = Path(self.temp.name).resolve() / 'app with spaces'
        (self.app / 'deploy').mkdir(parents=True)
        shutil.copy(ROOT / 'deploy/claw-agent.conf', self.app / 'deploy')
        (self.app / 'web-react/dist/assets').mkdir(parents=True)
        (self.app / 'web-react/dist/index.html').write_text('<html>SPA</html>')
        (self.app / 'web-react/dist/sw.js').write_text('// worker')
        self.runtime = self.app / '.data/deploy-mac'
        self.output = self.runtime / 'staging'
        self.web_port, self.api_port = free_port(), free_port()
        while self.web_port == self.api_port:
            self.api_port = free_port()
        self.nginx = shutil.which('nginx') or '/usr/local/bin/nginx'

    def generate(self, secure=False):
        mac.generate(self.app, self.runtime, self.output, self.app / '.venv/bin/python',
                     self.nginx, self.web_port, self.api_port, secure)

    def test_launch_agents_and_cookie_mode(self):
        for secure in (False, True):
            self.generate(secure)
            with (self.output / 'com.claw-agent.api.plist').open('rb') as stream:
                api = plistlib.load(stream)
            self.assertEqual(api['WorkingDirectory'], str(self.app))
            self.assertEqual(api['EnvironmentVariables']['WEB_HOST'], '127.0.0.1')
            self.assertEqual(api['EnvironmentVariables']['AUTH_COOKIE_SECURE'], str(secure).lower())
            self.assertEqual(api['ProgramArguments'][0], str(self.app / '.venv/bin/python'))
            self.assertTrue(api['KeepAlive'])
            with (self.output / 'com.claw-agent.web.plist').open('rb') as stream:
                web = plistlib.load(stream)
            self.assertIn('daemon off;', web['ProgramArguments'])
            self.assertEqual(json.loads((self.output / 'config.json').read_text())['web_port'], self.web_port)

    def test_first_deploy_accepts_unused_port_with_no_launch_job(self):
        # Keep errexit/pipefail enabled: an absent launchd job is normal on first deploy.
        result = subprocess.run(['/bin/bash', '-c', r'''source "$1"
launchctl() { return 113; }
lsof() { return 1; }
ask() { REPLY=18080; }
ask_port test 18080 web
[[ "$REPLY" == 18080 ]]
''', 'test', str(ROOT / 'deploy/mac.sh')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_ports(self):
        for web, api in ((80, 8000), (8080, 8080), (70000, 8000)):
            with self.assertRaises(ValueError):
                mac.generate(self.app, self.runtime, self.output, '/python', '/nginx', web, api, False)

    def test_nginx_path_encoding(self):
        self.assertEqual(mac.nginx_quote('/a "quoted"/file'), '"/a \\"quoted\\"/file"')
        for path in ('/a\nb', '/a\rb', '/a$b', '/a\x00b'):
            with self.assertRaises(ValueError):
                mac.nginx_quote(path)

    @unittest.skipUnless(shutil.which('nginx'), 'Nginx unavailable')
    def test_real_nginx_spa_proxy_cache_and_stream(self):
        class Origin(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                self.wfile.write(('data: ' + self.path + '\n\n').encode())
                self.wfile.flush()
                if self.path == '/api/stream':
                    time.sleep(0.6)
                    self.wfile.write(b'data: done\n\n')
            def log_message(self, *args):
                pass

        origin = ThreadingHTTPServer(('127.0.0.1', self.api_port), Origin)
        self.addCleanup(origin.server_close)
        self.addCleanup(origin.shutdown)
        threading.Thread(target=origin.serve_forever, daemon=True).start()
        self.generate()
        # A minimal MIME map suffices; production copies Homebrew's complete map.
        (self.runtime / 'mime.types').write_text('types { text/html html; application/javascript js; }')
        shutil.copy(self.output / 'nginx.conf', self.runtime / 'nginx.conf')
        command = [self.nginx, '-e', str(self.app / 'log/mac/nginx-error.log'), '-p', str(self.runtime) + '/', '-c', str(self.runtime / 'nginx.conf')]
        result = subprocess.run(command + ['-t'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        nginx = subprocess.Popen(command + ['-g', 'daemon off;'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        def stop():
            nginx.terminate()
            nginx.communicate(timeout=5)
        self.addCleanup(stop)
        opener = build_opener(ProxyHandler({}))
        base = f'http://127.0.0.1:{self.web_port}'
        for _ in range(50):
            try:
                with opener.open(base, timeout=1) as response:
                    self.assertIn(b'SPA', response.read())
                break
            except OSError:
                time.sleep(0.05)
        else:
            self.fail('Nginx never became ready')
        with opener.open(base + '/nested/route', timeout=2) as response:
            self.assertIn(b'SPA', response.read())
        for route in ('/api/health', '/files/example', '/generated/example'):
            with opener.open(base + route, timeout=2) as response:
                self.assertIn(route.encode(), response.read())
        with opener.open(base + '/sw.js', timeout=2) as response:
            self.assertEqual(response.headers['Cache-Control'], 'no-cache')
            self.assertEqual(response.headers['Service-Worker-Allowed'], '/')
        with self.assertRaises(HTTPError) as caught:
            opener.open(base + '/assets/missing.js', timeout=2)
        self.assertEqual(caught.exception.code, 404)
        started = time.monotonic()
        with opener.open(base + '/api/stream', timeout=2) as response:
            self.assertEqual(response.readline(), b'data: /api/stream\n')
            self.assertLess(time.monotonic() - started, 0.5, 'SSE was buffered')
            self.assertIn(b'data: done', response.read())


class MacRestartTest(unittest.TestCase):
    def run_shell(self, body):
        return subprocess.run(['/bin/bash', '-c', 'source "$1"\n' + body,
                               'test', str(ROOT / 'deploy/mac.sh')], capture_output=True, text=True)

    def test_stop_waits_until_launchd_removes_terminating_jobs(self):
        result = self.run_shell(r'''remaining=0
launchctl() {
  case "$1" in
    bootout) remaining=2 ;;
    print) [[ "$remaining" -ne -1 ]] ;;
  esac
}
sleep() { remaining=$((remaining-1)); if [[ "$remaining" -le 0 ]]; then remaining=-1; fi; }
stop_jobs
[[ "$remaining" == -1 ]]
''')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_stop_timeout_does_not_continue_to_start(self):
        result = self.run_shell(r'''launchctl() { return 0; }
sleep() { :; }
stop_jobs
echo SHOULD_NOT_START
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('等待服务退出超时', result.stderr)
        self.assertNotIn('SHOULD_NOT_START', result.stdout)


if __name__ == '__main__':
    unittest.main()
