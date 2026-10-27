"""013 browser acceptance against synthetic accounts and an isolated native model stub."""
from datetime import datetime, timezone
from pathlib import Path
import os
import signal
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def ready(url):
    for _ in range(100):
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200: return
        except OSError:
            time.sleep(.1)
    raise RuntimeError('Preview did not start: ' + url)


def main():
    api, web = free_port(), free_port()
    origin = f'http://127.0.0.1:{web}'
    env = {**os.environ, 'CARDS013_API_PORT': str(api), 'VITE_API_TARGET': f'http://127.0.0.1:{api}'}
    output = ROOT / '.data/validation/interactive-cards'
    output.mkdir(parents=True, exist_ok=True)
    processes = []
    try:
        processes.append(subprocess.Popen([sys.executable, str(ROOT / 'test/browser/interactive_cards_server.py')], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, start_new_session=True))
        ready(f'http://127.0.0.1:{api}/')
        processes.append(subprocess.Popen(['npm', '--prefix', str(ROOT / 'web-react'), 'run', 'dev', '--', '--host', '127.0.0.1', '--port', str(web), '--strictPort'], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, start_new_session=True))
        ready(origin)
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='chrome', headless=True)
            context = browser.new_context(viewport={'width': 1440, 'height': 1100}, locale='zh-CN', timezone_id='America/Los_Angeles')
            context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
            context.route('https://fonts.gstatic.com/**', lambda route: route.abort())
            assert context.request.post(origin + '/api/auth/login', data={'username': 'cards013', 'password': 'Cards013-test'}).ok
            page = context.new_page()
            page.clock.set_fixed_time(datetime(2026, 10, 27, 4, tzinfo=timezone.utc))
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(origin + '/chat')
            composer = page.locator('.composer-input')
            expect(composer).to_be_enabled()
            composer.fill('帮我创建日程，明天这个时候去上海')
            page.get_by_role('button', name='发送', exact=True).click()
            saved = page.get_by_role('article', name='日程卡片：去上海')
            expect(saved).to_be_visible(timeout=15000)
            expect(composer).to_be_enabled(timeout=15000)
            expect(saved).to_have_count(1)
            page.screenshot(path=str(output / 'created-desktop.png'))
            session_id = context.request.get(origin + '/api/sessions').json()[0]['id']
            rows = context.request.get(origin + '/api/home/tasks?view=visible').json()['items']
            assert len(rows) == 1
            task_id = rows[0]['task']['id']
            saved.get_by_role('button', name='调整事项').click()
            saved.get_by_label('标题', exact=True).fill('出发去上海')
            saved.get_by_label('时间（可选）').fill('15:00')
            saved.get_by_label('空间', exact=True).select_option('household')
            saved.get_by_label('小陈', exact=True).check()
            assert context.request.get(origin + '/api/home/tasks/' + task_id).json()['task']['title'] == '去上海'
            page.screenshot(path=str(output / 'editing-desktop.png'))
            saved.get_by_role('button', name='保存修改', exact=True).click()
            expect(page.get_by_role('article', name='日程卡片：出发去上海')).to_be_visible()
            detail = context.request.get(origin + '/api/home/tasks/' + task_id).json()
            assert detail['task']['space_type'] == 'household' and detail['task']['assignee_ids'] == ['A', 'B']
            assert detail['task']['id'] == task_id and detail['task']['due_at'].startswith('2026-10-28T07:00')
            assert context.request.get(origin + '/api/home/tasks?view=visible').json()['total'] == 1
            print('native creation -> one card -> atomic fields save passed', flush=True)

            page.goto(origin + '/home')
            calendar = page.get_by_role('complementary', name='日程月历')
            calendar.get_by_role('button', name='2026-10-28', exact=True).click()
            expect(calendar.get_by_text('出发去上海', exact=True)).to_be_visible()
            page.goto(origin + '/home/tasks?task=' + task_id)
            expect(page.get_by_role('dialog', name='事项详情')).to_be_visible()
            expect(page.get_by_role('dialog', name='事项详情').get_by_text('出发去上海', exact=True)).to_be_visible()
            print('calendar and family task detail synchronization passed', flush=True)

            page.goto(origin + '/sessions/' + session_id)
            saved = page.get_by_role('article', name='日程卡片：出发去上海')
            expect(saved).to_be_visible()
            for theme in ['light', 'dark']:
                page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                for width, height in [(1440, 1100), (390, 844)]:
                    page.set_viewport_size({'width': width, 'height': height})
                    if width < 768:
                        page.wait_for_function("document.querySelector('.sidebar').getBoundingClientRect().right <= 1")
                    expect(saved).to_be_visible()
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.screenshot(path=str(output / f'saved-{theme}-{width}.png'), full_page=True)
            page.set_viewport_size({'width': 390, 'height': 844})
            page.wait_for_function("document.querySelector('.sidebar').getBoundingClientRect().right <= 1")
            saved.get_by_role('button', name='调整事项').click()
            saved.get_by_label('标题', exact=True).fill('手机端保留的修改')
            page.screenshot(path=str(output / 'editing-mobile-dark.png'), full_page=True)
            saved.get_by_role('button', name='放弃修改', exact=True).click()
            print('history reload, mobile, light and dark layouts passed', flush=True)

            # Backend time advances while the same conversation remains open.
            assert context.request.post(origin + '/api/__test/clock', data={'now': '2026-10-29T00:00:00+08:00'}).ok
            page.evaluate("window.dispatchEvent(new Event('focus'))")
            expect(saved.get_by_text('已过期 · 只读', exact=True)).to_be_visible()
            expect(saved.get_by_role('button', name='调整事项')).to_have_count(0)
            page.screenshot(path=str(output / 'expired-mobile.png'), full_page=True)
            print('open historical card becomes read-only after midnight passed', flush=True)

            assert context.request.post(origin + '/api/__test/clock', data={'now': '2026-10-27T12:00:00+08:00'}).ok
            page.goto(origin + '/chat')
            expect(page.locator('.composer-input')).to_be_enabled()
            page.locator('.composer-input').fill('帮我创建日程草稿，去上海')
            page.get_by_role('button', name='发送', exact=True).click()
            draft = page.get_by_role('article', name='待补充事项卡片')
            expect(draft).to_be_visible(timeout=15000)
            expect(page.locator('.composer-input')).to_be_enabled(timeout=15000)
            draft.get_by_label('日期', exact=True).fill('2026-10-28')
            draft.get_by_role('button', name='创建事项', exact=True).click()
            expect(draft).to_have_count(0)
            expect(page.get_by_role('article', name='日程卡片：去上海')).to_be_visible()
            page.reload()
            expect(page.get_by_role('article', name='日程卡片：去上海')).to_be_visible()
            assert context.request.get(origin + '/api/home/tasks?view=visible').json()['total'] == 2
            assert not errors, errors
            print('incomplete draft -> direct date input -> create -> reload passed', flush=True)
            browser.close()
        print('013 browser acceptance passed. Screenshots: ' + str(output))
    finally:
        for process in reversed(processes):
            try: os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError: pass
        for process in reversed(processes):
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: os.killpg(process.pid, signal.SIGKILL)


if __name__ == '__main__':
    main()
