"""011 desktop/mobile browser checks, using isolated storage and a model stub.

Run with Python containing Playwright and installed Google Chrome.
"""
from pathlib import Path
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def ready(url):
    for _ in range(150):
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(.1)
    raise RuntimeError('Test server did not start')


def checks(origin, output):
    from playwright.sync_api import sync_playwright, expect
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        context = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, locale='zh-CN')
        context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
        context.route('https://fonts.gstatic.com/**', lambda route: route.abort())
        assert context.request.post(origin + '/api/auth/login', data={'username': 'library011', 'password': 'Library011-test'}).ok
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(origin + '/home/library')
        page.get_by_role('button', name='保存资料', exact=True).click()
        dialog = page.get_by_role('dialog', name='保存生活资料')
        dialog.get_by_label('选择文件').set_input_files({'name': '空调说明书.txt', 'mimeType': 'text/plain', 'buffer': '设备型号 AC-710。清洗滤网：先断电，再用清水冲洗。'.encode()})
        dialog.get_by_label('关联对象（选填）').fill('客厅空调')
        dialog.get_by_role('button', name='保存', exact=True).click()
        expect(dialog).not_to_be_visible()
        expect(page.get_by_role('button', name='空调说明书.txt', exact=False)).to_be_visible()
        page.screenshot(path=str(output / 'mobile-library.png'), full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')
        page.get_by_role('button', name='空调说明书.txt', exact=False).click()
        dialog = page.get_by_role('dialog')
        dialog.get_by_role('button', name='共享给家庭').click()
        dialog.get_by_role('button', name='确认共享').click()
        expect(dialog.get_by_text('家庭成员可见', exact=False)).to_be_visible()
        page.screenshot(path=str(output / 'mobile-detail.png'), full_page=True)
        page.get_by_role('button', name='返回', exact=True).click()
        # An independent family account can search the shared source.
        other = browser.new_context(viewport={'width': 1280, 'height': 900})
        other.route('https://fonts.googleapis.com/**', lambda route: route.abort())
        other.route('https://fonts.gstatic.com/**', lambda route: route.abort())
        other.request.post(origin + '/api/auth/login', data={'username': 'library011b', 'password': 'Library011-test'})
        family_page = other.new_page()
        family_page.goto(origin + '/home/library')
        expect(family_page.get_by_role('button', name='空调说明书.txt', exact=False)).to_be_visible()
        family_page.screenshot(path=str(output / 'desktop-family-library.png'), full_page=True)
        # Cross-session retrieval goes through the real runtime and sources.
        page.goto(origin + '/chat')
        page.locator('.composer-input').fill('之前的空调说明书，型号是什么')
        page.get_by_title('发送 (Enter)', exact=True).click()
        citation = page.get_by_role('link', name='核对来源', exact=True)
        expect(citation).to_be_visible(timeout=15000)
        source_url = citation.get_attribute('href')
        assert 'AC-710' in context.request.get(origin + source_url).text()
        page.screenshot(path=str(output / 'mobile-source-answer.png'), full_page=True)
        # Natural memory saves through native tools and appears in management.
        page.locator('.composer-input').fill('帮我记住：备用钥匙在玄关第二层抽屉')
        page.get_by_title('发送 (Enter)', exact=True).click()
        expect(page.locator('.messages-wrap').get_by_text('已记住，个人可见。', exact=True)).to_be_visible(timeout=15000)
        page.locator('#composer-file-input').set_input_files({'name': '补充资料.txt', 'mimeType': 'text/plain', 'buffer': '备用设备型号 EXTRA-22'.encode()})
        page.locator('.composer-input').fill('看看这份材料')
        page.get_by_title('发送 (Enter)', exact=True).click()
        page.get_by_role('button', name='保存到资料', exact=True).click()
        page.get_by_role('button', name='确认保存', exact=True).click()
        expect(page.get_by_role('link', name='查看资料', exact=True)).to_be_visible(timeout=15000)
        page.goto(origin + '/home/memories')
        page.get_by_role('button', name='备用钥匙位置', exact=False).click()
        dialog = page.get_by_role('dialog')
        expect(dialog).to_be_visible()
        page.screenshot(path=str(output / 'mobile-memory-editor.png'), full_page=True, animations='disabled')
        dialog.get_by_label('内容', exact=True).fill('备用钥匙改放在书房抽屉')
        dialog.get_by_role('button', name='保存', exact=True).click()
        expect(dialog).not_to_be_visible()
        page.screenshot(path=str(output / 'mobile-memories.png'), full_page=True)
        # Revoke access, then verify both search and previously issued source URL.
        page.goto(origin + '/home/library')
        page.get_by_role('button', name='空调说明书.txt', exact=False).click()
        dialog = page.get_by_role('dialog')
        dialog.get_by_role('button', name='撤回共享').click()
        expect(dialog.get_by_text('仅自己可见', exact=False)).to_be_visible()
        assert not other.request.get(origin + '/api/knowledge/search?q=AC-710').json()['items']
        assert other.request.get(origin + source_url).status == 404
        dialog.get_by_role('button', name='删除资料').click()
        dialog.get_by_role('button', name='确认删除').click()
        expect(dialog).not_to_be_visible()
        assert not context.request.get(origin + '/api/knowledge/search?q=AC-710').json()['items']
        assert not errors, errors
        browser.close()
        print('011 browser checks passed: mobile save, source, memory update, independent family access, revoke and delete.')


def main():
    api_port, web_port = port(), port()
    output = ROOT / '.data/validation/knowledge'
    output.mkdir(parents=True, exist_ok=True)
    processes = []
    with tempfile.TemporaryDirectory(prefix='knowledge011-') as data:
        env = {**os.environ, 'KNOWLEDGE_TEST_DATA': data, 'KNOWLEDGE_TEST_API_PORT': str(api_port),
               'VITE_API_TARGET': f'http://127.0.0.1:{api_port}'}
        try:
            processes.append(subprocess.Popen([sys.executable, str(ROOT / 'test/browser/knowledge_server.py')], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, start_new_session=True))
            ready(f'http://127.0.0.1:{api_port}/api/auth/usernames')
            processes.append(subprocess.Popen(['npm', '--prefix', str(ROOT / 'web-react'), 'run', 'dev', '--', '--host', '127.0.0.1', '--port', str(web_port), '--strictPort'], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, start_new_session=True))
            ready(f'http://127.0.0.1:{web_port}')
            checks(f'http://127.0.0.1:{web_port}', output)
        finally:
            for process in reversed(processes):
                try: os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError: pass
            for process in reversed(processes):
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: os.killpg(process.pid, signal.SIGKILL)


if __name__ == '__main__':
    main()
