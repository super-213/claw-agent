"""Validate the production PWA with Chrome and isolated example accounts.

Run `npm run web:build` first. Requires Python Playwright and Google Chrome.
No real users or model APIs are used. This supplements, not replaces, iPhone QA.
"""
from pathlib import Path
import json
import os
import signal
import shutil
import socket
import subprocess
import sys
import time
import tempfile
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.data/validation/pwa'
OUT.mkdir(parents=True, exist_ok=True)


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def wait_ready(url):
    for _ in range(120):
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(.1)
    raise RuntimeError(f'Preview failed to start: {url}')


api_port, web_port = free_port(), free_port()
origin = f'http://127.0.0.1:{web_port}'
env = {**os.environ, 'HOME010_API_PORT': str(api_port), 'VITE_API_TARGET': f'http://127.0.0.1:{api_port}'}
processes = []
results = []
worker_path = ROOT / 'web-react/dist/sw.js'
original_worker = worker_path.read_bytes()
try:
    processes.append(subprocess.Popen([sys.executable, str(ROOT / 'test/browser/home_workbench_server.py')], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, start_new_session=True))
    wait_ready(f'http://127.0.0.1:{api_port}/api/auth/usernames')
    nginx = shutil.which('nginx')
    mime = next((path for path in [Path('/etc/nginx/mime.types'), Path('/opt/homebrew/etc/nginx/mime.types')] if path.exists()), None)
    if nginx and mime:
        temporary = Path(tempfile.mkdtemp(prefix='claw-pwa-nginx-'))
        site = (ROOT / 'deploy/claw-agent.conf').read_text().replace('listen 80 default_server;', f'listen 127.0.0.1:{web_port};').replace('listen [::]:80 default_server;', '').replace('root /var/www/claw-agent;', f'root {ROOT}/web-react/dist;').replace('http://127.0.0.1:8000', f'http://127.0.0.1:{api_port}')
        config = temporary / 'nginx.conf'
        config.write_text(f'pid {temporary}/nginx.pid;\nerror_log stderr;\nevents {{}}\nhttp {{\ninclude {mime};\naccess_log off;\nclient_body_temp_path {temporary}/body;\nproxy_temp_path {temporary}/proxy;\n' + site + '\n}\n')
        subprocess.run([nginx, '-t', '-e', 'stderr', '-c', str(config)], check=True)
        processes.append(subprocess.Popen([nginx, '-e', 'stderr', '-c', str(config), '-g', 'daemon off;'], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, start_new_session=True))
    else:
        processes.append(subprocess.Popen(['npm', '--prefix', str(ROOT / 'web-react'), 'run', 'preview', '--', '--host', '127.0.0.1', '--port', str(web_port), '--strictPort'], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, start_new_session=True))
    wait_ready(origin)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        context = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, locale='zh-CN')
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(origin + '/install')
        expect(page.get_by_role('heading', name='把家庭助手放到主屏幕')).to_be_visible()
        expect(page.get_by_role('img', name='使用 iPhone 相机扫描，打开本站安装说明')).to_be_visible()
        manifest = context.request.get(origin + '/manifest.webmanifest').json()
        assert manifest['display'] == 'standalone' and manifest['id'] == '/home'
        for icon in manifest['icons']:
            assert context.request.get(origin + icon['src']).ok
        if nginx and mime:
            assert context.request.get(origin + '/sw.js').headers.get('cache-control') == 'no-cache'
            assert context.request.get(origin + '/manifest.webmanifest').headers.get('cache-control') == 'no-cache'
            assert context.request.get(origin + '/index.html').headers.get('cache-control') == 'no-cache'
            js = next((ROOT / 'web-react/dist/assets').glob('*.js')).name
            assert 'immutable' in context.request.get(origin + '/assets/' + js).headers.get('cache-control', '')
            for path in ['/assets/missing.js', '/missing.png', '/missing.webmanifest']:
                assert context.request.get(origin + path).status == 404, path
            assert context.request.get(origin + '/generated/private.png').status == 401
            assert context.request.get(origin + '/files/private.png').status == 401
            assert 'json' in context.request.get(origin + '/api/missing.png').headers.get('content-type', '')
            results.append('Nginx 缓存头、缺失资源 404 和私人图片认证路由通过')
        page.wait_for_function('navigator.serviceWorker.controller !== null')
        expect(page.get_by_role('button', name='更新', exact=True)).to_have_count(0)
        page.get_by_role('img', name='使用 iPhone 相机扫描，打开本站安装说明').scroll_into_view_if_needed()
        expect(page.get_by_role('img', name='使用 iPhone 相机扫描，打开本站安装说明')).to_be_in_viewport()
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(OUT / 'install-390.png'), full_page=True)
        results.append('安装说明、二维码、图标和 Worker 注册通过')

        # Exercise the real upload endpoint using temporary example users and files.
        assert context.request.post(origin + '/api/auth/login', data={'username': 'home010', 'password': 'Home010-test'}).ok
        page.goto(origin + '/chat')
        expect(page.locator('.composer-input')).to_be_enabled()
        page.locator('.composer-input').fill('保留这份草稿')
        page.get_by_role('button', name='添加文件或图片').click()
        sheet = page.get_by_role('dialog', name='添加附件')
        expect(sheet).to_be_visible()
        expect(sheet.get_by_role('button', name='拍照')).to_be_visible()
        expect(sheet.get_by_role('button', name='选择照片')).to_be_visible()
        sheet.get_by_role('button', name='关闭', exact=True).click()
        expect(sheet).to_have_count(0)
        expect(page.locator('.composer-input')).to_have_value('保留这份草稿')
        page.locator('#composer-file-input').set_input_files({'name': 'pwa-example.txt', 'mimeType': 'text/plain', 'buffer': b'PWA example only'})
        expect(page.locator('.composer-attachment')).to_contain_text('已上传')
        page.screenshot(path=str(OUT / 'chat-upload-390.png'))
        page.get_by_title('移除附件').click()
        results.append('附件面板、关闭后草稿保留和实际文件上传通过')

        # An expired upload session must not replace the page or discard text.
        page.route('**/api/chat/uploads', lambda route: route.fulfill(status=401, json={'message': '登录已过期'}), times=1)
        page.locator('#composer-file-input').set_input_files({'name': 'reauth-example.txt', 'mimeType': 'text/plain', 'buffer': b'reauthentication example'})
        reauth = page.get_by_role('dialog', name='登录已过期', exact=True)
        expect(reauth).to_be_visible()
        reauth.get_by_label('用户名', exact=True).fill('home010')
        reauth.get_by_label('密码', exact=True).fill('Home010-test')
        reauth.locator('button[type=submit]').click()
        expect(reauth).to_have_count(0)
        expect(page.locator('.composer-input')).to_have_value('保留这份草稿')
        page.get_by_role('button', name='重试', exact=True).click()
        expect(page.locator('.composer-attachment')).to_contain_text('已上传')
        page.get_by_title('移除附件').click()
        results.append('登录过期原页重新认证，保留草稿及附件重试通过')

        # Pointer drag must return or dismiss through the same dialog history.
        page.get_by_role('button', name='添加文件或图片').click()
        handle = page.locator('.pwa-sheet-handle')
        bounds = handle.bounding_box()
        x, y = bounds['x'] + bounds['width'] / 2, bounds['y'] + bounds['height'] / 2
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x, y + 130, steps=12)
        page.mouse.up()
        expect(sheet).to_have_count(0)
        expect(page.locator('.composer-input')).to_have_value('保留这份草稿')
        results.append('面板拖动关闭和草稿保持通过')

        # Model a smaller visual viewport independently of the layout viewport.
        page.locator('.composer-input').focus()
        page.evaluate('''() => {
          Object.defineProperty(visualViewport, 'height', { configurable: true, value: 420 });
          visualViewport.dispatchEvent(new Event('resize'));
        }''')
        page.wait_for_function("document.documentElement.classList.contains('keyboard-open')")
        box = page.locator('.composer-input').bounding_box()
        assert box['y'] + box['height'] <= 420, box
        expect(page.locator('.home-bottom-nav')).to_be_hidden()
        page.evaluate("delete visualViewport.height; visualViewport.dispatchEvent(new Event('resize'))")
        page.locator('.composer-input').blur()
        results.append('模拟键盘可视区域下输入框无遮挡且底部导航收起')

        # A published update must wait for drafts, then wait for other windows.
        worker_path.write_bytes(original_worker + b'\n// isolated PWA update validation\n')
        page.evaluate('''async () => {
          const reg = await navigator.serviceWorker.getRegistration();
          await reg.update();
        }''')
        expect(page.get_by_role('button', name='更新', exact=True)).to_be_visible(timeout=15000)
        page.get_by_role('button', name='更新', exact=True).click()
        expect(page.get_by_text('请先完成生成、上传并保存草稿或表单，再更新。')).to_be_visible()
        page.locator('.composer-input').fill('')
        other = context.new_page()
        other.goto(origin + '/install')
        page.get_by_role('button', name='更新', exact=True).click()
        expect(page.get_by_text('请关闭本站的其他窗口后再更新，以免打断其中的操作。')).to_be_visible()
        other.close()
        with page.expect_navigation():
            page.get_by_role('button', name='更新', exact=True).click()
        expect(page.locator('.composer-input')).to_be_enabled()
        results.append('真实 Worker 升级阻止草稿丢失和多窗口打断，安全时可完成升级')

        keys = page.evaluate('''async () => {
          const names = await caches.keys();
          return (await Promise.all(names.map(async name => (await (await caches.open(name)).keys()).map(r => r.url)))).flat();
        }''')
        assert keys and not any('/api/' in url or '/generated/' in url or '/files/' in url for url in keys), keys
        context.set_offline(True)
        page.goto(origin + '/install')
        expect(page.get_by_role('heading', name='把家庭助手放到主屏幕')).to_be_visible()
        expect(page.get_by_text('当前离线，已输入的内容会留在此页面。请联网后继续。')).to_be_visible()
        context.set_offline(False)
        results.append('离线启动和恢复联网通过，缓存没有业务 API 或私人文件')
        assert not errors, errors
        context.close()
        browser.close()
    (OUT / 'results.json').write_text(json.dumps({'checks': results, 'platform': 'Chrome with Nginx' if nginx and mime else 'Chrome production preview', 'iphone_verified': False, 'screenshots': ['install-390.png', 'chat-upload-390.png']}, ensure_ascii=False, indent=2))
    print('\n'.join(results), flush=True)
    print(f'PWA browser validation passed. Artifacts: {OUT}', flush=True)
finally:
    worker_path.write_bytes(original_worker)
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
