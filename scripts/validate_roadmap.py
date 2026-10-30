"""Production-browser acceptance: automatic data caching, WebAuthn, layouts.

Run npm run web:build first. Uses isolated accounts and Chrome virtual passkeys.
"""
from pathlib import Path
import json
import os
import signal
import socket
import subprocess
import sys
import time
from urllib.request import urlopen
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.data/validation/roadmap'
OUT.mkdir(parents=True, exist_ok=True)

def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]

def ready(url):
    for _ in range(150):
        try:
            if urlopen(url, timeout=1).status == 200:
                return
        except OSError:
            time.sleep(.1)
    raise RuntimeError('Browser acceptance server did not start')

api_port, web_port = port(), port()
origin = f'http://localhost:{web_port}'
node = os.environ.get('ROADMAP_NODE_DIR', '/Users/jiangzhihao/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin')
env = {**os.environ, 'HOME010_API_PORT': str(api_port), 'VITE_API_TARGET': f'http://127.0.0.1:{api_port}',
       'PASSKEY_ENABLED': 'true', 'PASSKEY_RP_ID': 'localhost', 'PASSKEY_ORIGIN': origin,
       'PATH': node + os.pathsep + os.environ['PATH']}
processes = []
skip_passkey = os.environ.get('ROADMAP_SKIP_PASSKEY') == '1'
try:
    api_log = (OUT / 'api.log').open('w')
    processes.append(subprocess.Popen([sys.executable, str(ROOT / 'test/browser/roadmap_server.py')], cwd=ROOT,
        env=env, stdout=api_log, stderr=api_log, start_new_session=True))
    ready(f'http://127.0.0.1:{api_port}/api/health')
    web_log = (OUT / 'web.log').open('w')
    processes.append(subprocess.Popen(['npm', '--prefix', str(ROOT / 'web-react'), 'run', 'preview', '--',
        '--host', 'localhost', '--port', str(web_port), '--strictPort'], cwd=ROOT, env=env,
        stdout=web_log, stderr=web_log, start_new_session=True))
    ready(origin)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 900}, locale='zh-CN')
        context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
        context.route('https://fonts.gstatic.com/**', lambda route: route.abort())
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('response', lambda response: print('HTTP failure:', response.status, response.url, flush=True) if response.status >= 400 else None)
        page.goto(origin + '/login')
        page.get_by_label('用户名', exact=True).fill('home010')
        page.get_by_label('密码', exact=True).fill('Home010-test')
        page.get_by_role('button', name='登录', exact=True).click()
        try:
            page.wait_for_url('**/home', timeout=10000)
        except Exception:
            page.screenshot(path=str(OUT / 'login-failed.png'))
            print('Login failed:', page.url, page.locator('.skill-form-error').all_text_contents(), errors, flush=True)
            raise
        page.wait_for_function('navigator.serviceWorker.controller !== null')
        # Native popover keyboard behavior and responsive container layouts.
        for width in (390, 768, 1440):
            page.set_viewport_size({'width': width, 'height': 900})
            page.goto(origin + '/home')
            trigger = page.get_by_role('button', name='家庭 Agent 快捷导航')
            if width > 767:
                trigger.click()
                popover = page.locator('.home-agent-popover')
                expect(popover).to_be_visible()
                page.keyboard.press('ArrowDown')
                assert page.evaluate("document.activeElement.closest('.home-agent-popover') !== null")
                page.keyboard.press('Escape')
                expect(popover).to_have_count(0)
            else:
                expect(page.get_by_role('navigation', name='手机主导航')).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(OUT / f'home-{width}.png'))
        # Cache full data through the regular UI; no opt-in page or button.
        page.goto(origin + '/chat')
        expect(page.get_by_role('heading', name='周末准备清单')).to_be_visible()
        page.wait_for_load_state('networkidle')
        page.goto(origin + '/home/items')
        expect(page.get_by_text('示例·牛奶', exact=False).first).to_be_visible()
        page.wait_for_load_state('networkidle')
        context.set_offline(True)
        page.reload()
        expect(page.get_by_text('示例·牛奶', exact=False).first).to_be_visible()
        expect(page.get_by_text('当前离线，已缓存的数据可继续查看，内容可能不是最新。修改与 AI 操作需要联网。')).to_be_visible()
        page.screenshot(path=str(OUT / 'automatic-cache-home.png'))
        page.goto(origin + '/chat')
        expect(page.get_by_role('heading', name='周末准备清单')).to_be_visible()
        page.screenshot(path=str(OUT / 'automatic-cache-chat.png'))
        context.set_offline(False)
        page.goto(origin + '/offline')
        page.wait_for_url('**/home')
        other = context.new_page()
        other.add_init_script('delete window.BroadcastChannel')
        other.goto(origin + '/home')
        expect(other.locator('.home-shell')).to_be_visible()
        # Real browser registration/login against a virtual authenticator.
        page.bring_to_front()
        if not skip_passkey:
            cdp = context.new_cdp_session(page)
            cdp.send('WebAuthn.enable')
            cdp.send('WebAuthn.addVirtualAuthenticator', {'options': {'protocol': 'ctap2', 'transport': 'internal',
                'hasResidentKey': True, 'hasUserVerification': True, 'isUserVerified': True,
                'automaticPresenceSimulation': True}})
            page.goto(origin + '/home/more?section=account')
            page.get_by_label('当前密码（新增与移除时验证）').fill('Home010-test')
            page.get_by_role('button', name='添加通行密钥').click()
            expect(page.get_by_role('button', name='移除此密钥')).to_be_visible()
        else:
            page.goto(origin + '/home/more?section=account')
        page.get_by_role('button', name='退出登录', exact=True).click()
        page.wait_for_url('**/login')
        other.wait_for_url('**/login')
        page.get_by_label('用户名', exact=True).fill('home010')
        if skip_passkey:
            page.get_by_label('密码', exact=True).fill('Home010-test')
            page.get_by_role('button', name='登录', exact=True).click()
        else:
            page.get_by_role('button', name='使用通行密钥登录').click()
        page.wait_for_url('**/home')
        # Account switch leaves no previous user response in IndexedDB.
        page.goto(origin + '/home/more?section=account')
        page.get_by_role('button', name='退出登录', exact=True).click()
        page.wait_for_url('**/login')
        page.get_by_label('用户名', exact=True).fill('home010b')
        page.get_by_label('密码', exact=True).fill('Home010-test')
        page.get_by_role('button', name='登录', exact=True).click()
        page.wait_for_url('**/home')
        cached_owner = page.evaluate("localStorage.getItem('claw-response-cache-owner')")
        assert cached_owner == context.request.get(origin + '/api/auth/me').json()['user']['id']
        assert page.evaluate('''async () => {
            const db = await new Promise((resolve, reject) => {
                const req = indexedDB.open('claw-response-cache', 1);
                req.onsuccess = () => resolve(req.result); req.onerror = reject;
            });
            const rows = await new Promise((resolve, reject) => {
                const req = db.transaction('responses').objectStore('responses').getAll();
                req.onsuccess = () => resolve(req.result); req.onerror = reject;
            });
            db.close();
            return rows.every(row => row.owner === localStorage.getItem('claw-response-cache-owner'));
        }''')
        other.close()
        page.emulate_media(reduced_motion='reduce')
        page.goto(origin + '/home')
        assert page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
        assert not errors, errors
        browser.close()
        (OUT / 'result.json').write_text(json.dumps({'status': 'passed', 'checks': [
            '390/768/1440 layouts', 'native popover keyboard and Escape', 'offline reload',
            'automatic full page and conversation cache', *([] if skip_passkey else ['WebAuthn browser registration and login']),
            'logout/account cache isolation', 'cross-tab storage fallback', 'reduced motion', 'no page errors'], 'skipped': ['WebAuthn browser registration and login'] if skip_passkey else []}, ensure_ascii=False, indent=2))
        print('Roadmap browser acceptance passed: ' + str(OUT))
finally:
    for process in reversed(processes):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: os.killpg(process.pid, signal.SIGKILL)
