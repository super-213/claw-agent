"""Production browser check for detached chat and Web Push wiring.

Uses synthetic users, a delayed model stub, and captured push transport only.
Chrome DevTools injects a push into the service worker; no external push is sent.
"""
import base64
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.data/validation/chat-notifications'
OUT.mkdir(parents=True, exist_ok=True)
capture = OUT / 'push.jsonl'
capture.unlink(missing_ok=True)


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def ready(url):
    for _ in range(100):
        try:
            if urlopen(url, timeout=1).status == 200:
                return
        except Exception:
            time.sleep(.1)
    raise RuntimeError('Server did not start: ' + url)


api_port, web_port = free_port(), free_port()
origin = f'http://127.0.0.1:{web_port}'
env = {**os.environ, 'HOME010_API_PORT': str(api_port), 'VITE_API_TARGET': f'http://127.0.0.1:{api_port}', 'HOME010_MODEL_DELAY': '2', 'HOME010_CAPTURE_PUSH': str(capture), 'WEB_PUSH_SUBJECT': 'mailto:pwa-validation@example.com'}
processes = []
try:
    processes.append(subprocess.Popen([sys.executable, str(ROOT / 'test/browser/home_workbench_server.py')], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, start_new_session=True))
    ready(f'http://127.0.0.1:{api_port}/api/auth/usernames')
    processes.append(subprocess.Popen(['npm', '--prefix', str(ROOT / 'web-react'), 'run', 'preview', '--', '--host', '127.0.0.1', '--port', str(web_port), '--strictPort'], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, start_new_session=True))
    ready(origin)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        context = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, locale='zh-CN', permissions=['notifications'])
        assert context.request.post(origin + '/api/auth/login', data={'username': 'home010', 'password': 'Home010-test'}).ok
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(origin + '/home/more?section=account')
        page.wait_for_function('navigator.serviceWorker.controller !== null')
        # Replace browser transport only; the settings UI and authenticated API are real.
        page.evaluate('''async () => {
          const reg = await navigator.serviceWorker.getRegistration('/');
          const encode = s => btoa(s).replaceAll('+','-').replaceAll('/','_').replaceAll('=','');
          const value = {endpoint: 'https://web.push.apple.com/browser-validation', keys: {
            p256dh: encode(String.fromCharCode(4) + '\\0'.repeat(64)), auth: encode('\\0'.repeat(16))}};
          let subscription = null;
          Object.defineProperty(reg, 'pushManager', {value: {
            getSubscription: async () => subscription,
            subscribe: async () => subscription = {toJSON: () => value, endpoint: value.endpoint, unsubscribe: async () => true}
          }});
        }''')
        page.get_by_role('button', name='开启回复通知', exact=True).click()
        expect(page.get_by_role('button', name='关闭回复通知', exact=True)).to_be_visible()
        page.screenshot(path=str(OUT / 'notification-settings.png'), full_page=True)
        page.goto(origin + '/chat')
        expect(page.locator('.composer-input')).to_be_enabled()
        question = '/ 日程 今天新增后台生成示例'
        page.locator('.composer-input').fill(question)
        with page.expect_response(lambda response: response.url.endswith('/api/chat/jobs') and response.request.method == 'POST') as created:
            page.get_by_role('button', name='发送', exact=True).click()
        job = created.value.json()['job']
        page.close()
        # No window is reading or acknowledging completion.
        for _ in range(150):
            state = context.request.get(origin + '/api/chat/jobs/' + job['id']).json()['job']
            if state['status'] not in ('queued', 'running'):
                break
            time.sleep(.1)
        assert state['status'] == 'succeeded', state
        detail = context.request.get(origin + '/api/sessions/' + job['session_id']).json()
        assert any(message.get('content') == '示例日程已记录。' for message in detail['messages']), detail
        for _ in range(100):
            if capture.exists() and capture.read_text().strip():
                break
            time.sleep(.1)
        notices = [json.loads(line) for line in capture.read_text().splitlines()]
        assert len(notices) == 1, notices
        assert notices[0]['job_id'] == job['id']
        assert '后台生成示例' not in json.dumps(notices, ensure_ascii=False)
        assert notices[0]['url'] == '/sessions/' + job['session_id']
        print('关闭全部页面后任务完成、回复持久化、通知队列去重与隐私内容通过', flush=True)

        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(origin + notices[0]['url'])
        expect(page.get_by_text('示例日程已记录。', exact=True).first).to_be_visible()
        expect(page.locator('.composer-input')).to_be_enabled()
        page.screenshot(path=str(OUT / 'reopened-result.png'))

        # Exercise the real SW push handler through Chrome's test interface.
        cdp = context.new_cdp_session(page)
        registrations = []
        cdp.on('ServiceWorker.workerRegistrationUpdated', lambda event: registrations.extend(event['registrations']))
        cdp.send('ServiceWorker.enable')
        for _ in range(30):
            if registrations:
                break
            page.wait_for_timeout(100)
        registration = next(item for item in registrations if item['scopeURL'] == origin + '/')
        cdp.send('ServiceWorker.deliverPushMessage', {'origin': origin, 'registrationId': registration['registrationId'], 'data': json.dumps(notices[0], ensure_ascii=False)})
        page.wait_for_function('''async () => (await (await navigator.serviceWorker.getRegistration()).getNotifications()).some(n => n.tag.startsWith('chat-'))''')
        displayed = page.evaluate('''async () => (await (await navigator.serviceWorker.getRegistration()).getNotifications()).map(n => ({title:n.title,body:n.body,url:n.data.url}))''')
        assert displayed[0]['title'] == '回复已完成' and displayed[0]['url'] == notices[0]['url']

        # Reading the result suppresses a duplicate notification.
        with page.expect_response(lambda response: '/api/chat/jobs/' in response.url and response.url.endswith('/read') and response.request.method == 'POST'):
            page.locator('.composer-input').fill('/ 日程 今天新增前台阅读示例')
            page.get_by_role('button', name='发送', exact=True).click()
        page.wait_for_timeout(7500)
        assert len(capture.read_text().splitlines()) == 1

        # A retained chat mounted behind the home route must not acknowledge a reply.
        page.locator('.composer-input').fill('/ 日程 今天新增首页等待示例')
        with page.expect_response(lambda response: response.url.endswith('/api/chat/jobs') and response.request.method == 'POST') as home_created:
            page.get_by_role('button', name='发送', exact=True).click()
        home_job = home_created.value.json()['job']
        page.locator('.home-bottom-nav').get_by_role('link', name='工作台', exact=True).click()
        expect(page.locator('.chat-workspace')).not_to_be_visible()
        for _ in range(180):
            if len(capture.read_text().splitlines()) == 2:
                break
            page.wait_for_timeout(100)
        final_notices = [json.loads(line) for line in capture.read_text().splitlines()]
        assert len(final_notices) == 2 and final_notices[-1]['job_id'] == home_job['id'], final_notices
        print('正在阅读时免打扰、返回首页后仍通知通过', flush=True)
        assert context.request.post(origin + '/api/auth/logout').ok
        assert context.request.post(origin + '/api/auth/login', data={'username': 'home010', 'password': 'Home010-test'}).ok
        assert not any(item['enabled'] for item in context.request.get(origin + '/api/chat-notifications').json()['devices'])
        print('重新打开结果、开发工具注入推送显示、退出登录撤销订阅通过', flush=True)
        assert not errors, errors
        (OUT / 'results.json').write_text(json.dumps({'closed_page_job': state, 'push_count': len(final_notices), 'foreground_suppressed': True, 'home_result_notified': True, 'service_worker_notifications': displayed, 'external_push_sent': False, 'iphone_verified': False}, ensure_ascii=False, indent=2))
        context.close()
        browser.close()
    print('Chat notification browser validation passed: ' + str(OUT), flush=True)
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
