"""014 browser acceptance: real HTTP, synthetic accounts and a deterministic native model."""
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import os
import signal
import socket
import subprocess
import sys
import time
from urllib.request import urlopen
from PIL import Image
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
        except OSError: time.sleep(.1)
    raise RuntimeError('Preview did not start: ' + url)


def main():
    api, web = free_port(), free_port()
    origin = f'http://127.0.0.1:{web}'
    env = {**os.environ, 'BOARD014_API_PORT': str(api), 'VITE_API_TARGET': f'http://127.0.0.1:{api}'}
    output = ROOT / '.data/validation/board'
    output.mkdir(parents=True, exist_ok=True)
    processes = []
    try:
        processes.append(subprocess.Popen([sys.executable, str(ROOT / 'test/browser/board_server.py')], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, start_new_session=True))
        ready(f'http://127.0.0.1:{api}/')
        processes.append(subprocess.Popen(['npm', '--prefix', str(ROOT / 'web-react'), 'run', 'dev', '--', '--host', '127.0.0.1', '--port', str(web), '--strictPort'], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, start_new_session=True))
        ready(origin)
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='chrome', headless=True)
            context = browser.new_context(viewport={'width': 1440, 'height': 1100}, locale='zh-CN', timezone_id='America/Los_Angeles')
            context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
            context.route('https://fonts.gstatic.com/**', lambda route: route.abort())
            assert context.request.post(origin + '/api/auth/login', data={'username': 'board014', 'password': 'Board014-test'}).ok
            page = context.new_page()
            page.clock.set_fixed_time(datetime(2026, 10, 27, 4, tzinfo=timezone.utc))
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(origin + '/home')
            expect(page.get_by_role('button', name='自定义', exact=True)).to_be_visible()
            page.get_by_role('button', name='留言板', exact=True).click()
            page.get_by_role('button', name='写便笺', exact=True).click()
            editor = page.get_by_role('dialog', name='写便笺', exact=True)
            expect(editor).to_be_visible()
            editor.get_by_label('便笺标题').fill('晚饭在冰箱里')
            editor.get_by_label('便笺正文 1').fill('今晚的饭在冰箱第二层，热一下就可以吃。\n' * 35)
            editor.get_by_label('小陈', exact=True).check()
            photo = BytesIO()
            Image.new('RGB', (480, 320), '#c9bda3').save(photo, 'PNG')
            editor.locator('input[type=file]').set_input_files({'name': 'dinner.png', 'mimeType': 'image/png', 'buffer': photo.getvalue()})
            expect(editor.get_by_role('button', name='发布便笺', exact=True)).to_be_enabled()
            editor.get_by_label('便笺保留方式').select_option('until')
            editor.get_by_label('便笺截止时间').fill('2026-10-27T18:00')
            # Closing and opening resumes the same draft and local edits.
            editor.get_by_role('button', name='返回', exact=True).click()
            expect(editor).not_to_be_visible()
            page.get_by_role('button', name='写便笺', exact=True).click()
            expect(editor.get_by_label('便笺标题')).to_have_value('晚饭在冰箱里')
            editor.get_by_role('button', name='发布便笺', exact=True).click()
            expect(editor.get_by_text('已发布', exact=True)).to_be_visible()
            editor.get_by_role('button', name='返回', exact=True).click()
            note = page.get_by_role('article', name='便笺：晚饭在冰箱里', exact=True)
            expect(note).to_be_visible()
            page.screenshot(path=str(output / 'initial.png'), full_page=True, animations='disabled')
            print('note geometry', note.bounding_box(), note.evaluate('(el) => ({height:getComputedStyle(el).height,box:getComputedStyle(el).boxSizing,flex:getComputedStyle(el).flex})'), flush=True)
            assert note.evaluate('el => parseFloat(getComputedStyle(el).height)') == 320
            body = note.locator('.board-note-body')
            assert body.evaluate('(el) => el.scrollHeight > el.clientHeight')
            body.evaluate('(el) => el.scrollTop = 200')
            expect(page.get_by_role('dialog')).to_have_count(0)
            note.get_by_role('button', name='查看详情', exact=True).click()
            detail = page.get_by_role('dialog', name='便笺详情', exact=True)
            expect(detail).to_be_visible()
            detail.get_by_role('button', name='查看便笺图片', exact=True).click()
            expect(page.get_by_role('dialog', name='便笺图片', exact=True)).to_be_visible()
            page.keyboard.press('Escape')
            expect(detail).to_be_visible()
            page.keyboard.press('Escape')
            expect(detail).not_to_be_visible()
            # Card body click opens, while scrolling and selecting text do not.
            note.get_by_role('button', name='查看详情', exact=True).click()
            expect(detail).to_be_visible()
            page.locator('.home-dialog-backdrop').click(position={'x': 4, 'y': 4})
            expect(detail).not_to_be_visible()
            for theme in ['light', 'dark']:
                page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                for width, height in [(1440, 1100), (390, 844)]:
                    page.set_viewport_size({'width': width, 'height': height})
                    expect(note).to_be_visible()
                    expect(page.locator('.board-note-compact')).to_have_count(1 if width < 768 else 0)
                    assert note.evaluate('el => parseFloat(getComputedStyle(el).height)') == (210 if width < 768 else 320)
                    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                    page.screenshot(path=str(output / f'board-{theme}-{width}.png'), full_page=True, animations='disabled')
                    note.get_by_role('button', name='查看' if width < 768 else '查看详情', exact=True).click()
                    expect(detail).to_be_visible()
                    page.screenshot(path=str(output / f'detail-{theme}-{width}.png'), full_page=True, animations='disabled')
                    detail.get_by_role('button', name='返回', exact=True).click()
            page.set_viewport_size({'width': 1440, 'height': 1100})
            print('manual text/image, resume draft, fixed scrolling paper, nested return, themes and mobile passed', flush=True)
            listing = context.request.get(origin + '/api/home/board/posts').json()['items']
            post = listing[0]['post']
            assert post['expires_at'] == '2026-10-27T10:00:00+00:00'
            asset = next(b['asset_id'] for b in post['content_blocks'] if b['type'] == 'image')
            bob = browser.new_context(viewport={'width': 1440, 'height': 1100})
            assert bob.request.post(origin + '/api/auth/login', data={'username': 'board014b', 'password': 'Board014-test'}).ok
            bob_page = bob.new_page()
            bob_page.goto(origin + '/home?panel=board')
            expect(bob_page.get_by_role('article', name='便笺：晚饭在冰箱里')).to_be_visible()
            assert bob.request.get(origin + '/api/home/board/assets/' + asset).ok
            carol = browser.new_context()
            carol.request.post(origin + '/api/auth/login', data={'username': 'board014c', 'password': 'Board014-test'})
            assert not carol.request.get(origin + '/api/home/board/posts').json()['items']
            assert carol.request.get(origin + '/api/home/board/assets/' + asset).status == 404
            print('real member B can read, C cannot read either note or image passed', flush=True)
            page.goto(origin + '/chat')
            composer = page.locator('.composer-input')
            expect(composer).to_be_enabled()
            composer.fill('@ ')
            page.get_by_role('option', name='小陈', exact=True).click()
            expect(composer).to_have_value('@ 小陈 ')
            composer.fill('@ 小陈 帮我先写一张便笺，照片已经整理好。')
            page.get_by_role('button', name='发送', exact=True).click()
            card = page.get_by_role('article', name='便笺草稿卡片', exact=True)
            expect(card).to_be_visible(timeout=15000)
            expect(card.get_by_label('小陈', exact=True)).to_be_checked()
            card.get_by_label('小周', exact=True).check()
            card.get_by_role('button', name='发布便笺', exact=True).click()
            saved = page.get_by_role('article', name='便笺卡片：Agent 的留言', exact=True)
            expect(saved).to_be_visible()
            saved.get_by_role('button', name='在留言板查看', exact=True).click()
            expect(page.get_by_role('dialog', name='便笺详情')).to_be_visible()
            page.get_by_role('dialog', name='便笺详情').get_by_role('button', name='返回', exact=True).click()
            expect(page.get_by_role('article', name='便笺：Agent 的留言')).to_be_visible()
            print('bare @ picker -> native draft -> interactive multi-member publish -> board detail passed', flush=True)
            context.request.post(origin + '/api/__test/clock', data={'now': '2026-10-27T18:00:00+08:00'})
            page.reload()
            expect(page.get_by_role('article', name='便笺：晚饭在冰箱里')).to_have_count(0)
            expect(page.get_by_role('combobox', name='便笺状态')).to_have_count(0)
            expect(page.get_by_role('combobox', name='便笺来源')).to_have_count(0)
            assert context.request.get(origin + '/api/home/board/posts/' + post['id']).status == 404
            assert context.request.get(origin + '/api/home/board/assets/' + asset).status == 404
            assert bob.request.get(origin + '/api/home/board/assets/' + asset).status == 404
            assert all(row['post']['id'] != post['id'] for row in context.request.get(origin + '/api/home/board/posts?state=expired').json()['items'])
            # Expiration also occurs automatically while the page is open.
            context.request.post(origin + '/api/__test/clock', data={'now': '2026-10-27T18:00:00+08:00', 'ticking': True})
            short = context.request.post(origin + '/api/home/board/posts', data={'request_id': 'short-expiry', 'data': {
                'title': '短时便笺', 'content_blocks': [{'type': 'text', 'text': '到期自动销毁'}],
                'audience_mode': 'household', 'recipient_ids': [], 'retention_mode': 'until', 'duration_hours': .001}}).json()['post']
            page.reload()
            timed = page.get_by_role('article', name='便笺：短时便笺')
            expect(timed).to_be_visible()
            expect(timed).not_to_be_visible(timeout=6000)
            context.request.post(origin + '/api/__test/clock', data={'now': '2026-10-27T18:00:02+08:00'})
            assert context.request.get(origin + '/api/home/board/posts/' + short['id']).status == 404
            print('unfiltered personal feed, automatic on-screen expiry, destroyed notes/images and inaccessible old links passed', flush=True)
            assert not errors, errors
            browser.close()
    finally:
        for process in reversed(processes):
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)


if __name__ == '__main__': main()
