"""016 isolated browser flow; synthetic accounts, local clock, no external model/push."""
from pathlib import Path
import os
import signal
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from validate_board import free_port, ready
from playwright.sync_api import sync_playwright, expect


def main():
    api, web = free_port(), free_port()
    origin = f'http://127.0.0.1:{web}'
    env = {**os.environ, 'BOARD014_API_PORT': str(api), 'VITE_API_TARGET': f'http://127.0.0.1:{api}'}
    output = ROOT / '.data/validation/family-activities'
    output.mkdir(parents=True, exist_ok=True)
    processes = []
    try:
        processes.append(subprocess.Popen([sys.executable, str(ROOT / 'test/browser/board_server.py')], env=env, cwd=ROOT, stdout=subprocess.DEVNULL, start_new_session=True))
        ready(f'http://127.0.0.1:{api}/')
        processes.append(subprocess.Popen(['npm', '--prefix', str(ROOT / 'web-react'), 'run', 'dev', '--', '--host', '127.0.0.1', '--port', str(web), '--strictPort'], env=env, cwd=ROOT, stdout=subprocess.DEVNULL, start_new_session=True))
        ready(origin)
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='chrome', headless=True)
            contexts = [browser.new_context(viewport={'width': 1440, 'height': 900}, timezone_id='America/Los_Angeles', locale='zh-CN') for _ in range(3)]
            pages, errors = [], []
            for context, suffix in zip(contexts, ['', 'b', 'c']):
                context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
                context.route('https://fonts.gstatic.com/**', lambda route: route.abort())
                assert context.request.post(origin + '/api/auth/login', data={'username': 'board014' + suffix, 'password': 'Board014-test'}).ok
                page = context.new_page(); page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(origin + '/home?panel=board'); pages.append(page)
            page = pages[0]
            page.get_by_role('button', name='工具', exact=True).click()
            expect(page.get_by_role('menu', name='家庭工具')).to_be_visible()
            page.keyboard.press('Escape')
            expect(page.get_by_role('menu')).to_have_count(0)
            page.get_by_role('button', name='工具', exact=True).click()
            page.get_by_role('menuitem', name='新建家庭投票').click()
            editor = page.get_by_role('dialog', name='新建家庭投票', exact=True)
            expect(editor).to_be_visible()
            editor.get_by_label('标题', exact=True).fill('周末吃什么')
            editor.get_by_label('选项 1', exact=True).fill('火锅')
            editor.get_by_label('选项 2', exact=True).fill('烧烤')
            editor.get_by_label('参与截止（到点结束）', exact=False).fill('2026-10-27T20:00')
            editor.get_by_label('存在截止（到点自动销毁）', exact=False).fill('2026-10-28T20:00')
            # Draft identity and local form survive closing the dialog.
            editor.get_by_role('button', name='返回', exact=True).click()
            page.get_by_role('button', name='工具', exact=True).click(); page.get_by_role('menuitem', name='新建家庭投票').click()
            expect(editor.get_by_label('标题', exact=True)).to_have_value('周末吃什么')
            editor.get_by_role('button', name='发布家庭投票', exact=True).click()
            expect(editor.get_by_text('进行中', exact=True)).to_be_visible()
            editor.get_by_label('火锅', exact=False).check()
            editor.get_by_role('button', name='提交投票', exact=True).click()
            expect(editor.get_by_text('1 人已参与 · 你已参与', exact=True)).to_be_visible()
            editor.get_by_role('button', name='返回', exact=True).click()
            listing = contexts[0].request.get(origin + '/api/home/polls').json()['items']
            poll = listing[0]['activity']; identifier = poll['id']
            assert poll['participation_deadline_at'] == '2026-10-27T12:00:00+00:00'
            for other in pages[1:]:
                other.goto(origin + '/home?panel=board&activity=' + identifier)
                detail = other.get_by_role('dialog', name='家庭投票', exact=True)
                expect(detail).to_be_visible()
                detail.get_by_label('烧烤', exact=False).check()
                detail.get_by_role('button', name='提交投票', exact=True).click()
                expect(detail.get_by_text('你已参与', exact=False)).to_be_visible()
            page.reload()
            page.get_by_role('article', name='家庭投票：周末吃什么', exact=True).get_by_role('button', name='查看详情', exact=True).click()
            detail = page.get_by_role('dialog', name='家庭投票', exact=True)
            expect(detail.get_by_text('全员已完成，结果只读。', exact=True)).to_be_visible()
            expect(detail.get_by_role('button', name='提交投票')).to_have_count(0)
            for theme in ['light', 'dark']:
                page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                for width in [1440, 390]:
                    page.set_viewport_size({'width': width, 'height': 900 if width > 400 else 844})
                    expect(detail).to_be_visible()
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.screenshot(path=str(output / f'poll-{theme}-{width}.png'), full_page=True)
            page.set_viewport_size({'width': 1440, 'height': 900})
            detail.get_by_role('button', name='返回', exact=True).click()
            expect(page.get_by_role('button', name='家庭活动通知', exact=False)).to_have_count(0)
            expect(page.get_by_role('button', name='通知', exact=True)).to_have_count(0)
            notices = contexts[0].request.get(origin + '/api/home/notifications').json()['notifications']
            assert len(notices) == 1 and not notices[0]['read_at']
            assert contexts[1].request.get(origin + '/api/home/notifications').json()['notifications'] == []
            # End notifications and their activity deep links remain available without a toolbar inbox.
            page.goto(origin + notices[0]['url'])
            expect(page.get_by_role('dialog', name='家庭投票', exact=True)).to_be_visible()
            page.get_by_role('dialog').get_by_role('button', name='返回', exact=True).click()
            print('PASS poll: manual draft, publish, three real members, early close, notification, themes/mobile/timezone', flush=True)
            page.get_by_role('button', name='工具', exact=True).click(); page.get_by_role('menuitem', name='新建家庭接龙').click()
            editor = page.get_by_role('dialog', name='新建家庭接龙', exact=True)
            editor.get_by_label('标题', exact=True).fill('家庭采购接龙')
            editor.get_by_label('存在截止（到点自动销毁）', exact=False).fill('2026-10-27T13:00')
            editor.get_by_role('button', name='发布家庭接龙', exact=True).click()
            editor.get_by_label('接龙内容（必填）', exact=True).fill('牛奶 2 瓶')
            editor.get_by_role('button', name='加入接龙', exact=True).click()
            expect(editor.get_by_text('牛奶 2 瓶', exact=True)).to_be_visible()
            editor.get_by_role('button', name='返回', exact=True).click()
            for theme in ['light', 'dark']:
                page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                for width in [1440, 390]:
                    page.set_viewport_size({'width': width, 'height': 900 if width > 400 else 844})
                    expect(page.get_by_role('article', name='家庭接龙：家庭采购接龙')).to_be_visible()
                    page.screenshot(path=str(output / f'board-{theme}-{width}.png'), full_page=True)
            relay = contexts[0].request.get(origin + '/api/home/relays').json()['items'][0]['resource']['id']
            assert contexts[0].request.post(origin + '/api/__test/clock', data={'now': '2026-10-27T13:00:00+08:00'}).ok
            assert contexts[0].request.get(origin + '/api/home/relays/' + relay).status == 404
            page.reload()
            expect(page.get_by_role('article', name='家庭接龙：家庭采购接龙')).to_have_count(0)
            assert contexts[0].request.post(origin + '/api/__test/clock', data={'now': '2026-10-28T20:00:00+08:00'}).ok
            assert contexts[0].request.get(origin + '/api/home/polls/' + identifier).status == 404
            assert contexts[0].request.get(origin + '/api/home/notifications').json()['notifications'] == []
            print('PASS relay: create, join, mixed board; expiration destroys relay/poll and notifications', flush=True)
            assert not errors, errors
            browser.close()
    finally:
        for process in reversed(processes):
            try: os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError: pass
            process.wait(timeout=10)


if __name__ == '__main__': main()
