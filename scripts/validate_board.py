"""014 browser acceptance: real HTTP, synthetic accounts and a deterministic native model."""
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import os
import re
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
    env = {**os.environ, 'BOARD014_API_PORT': str(api), 'BOARD_UPLOAD_DELAY': '2', 'VITE_API_TARGET': f'http://127.0.0.1:{api}'}
    if os.getenv('BOARD_PICKER_FOCUS') == '1': env['BOARD_CARD_READ_DELAY'] = '2'
    output = ROOT / '.data/validation/board'
    output.mkdir(parents=True, exist_ok=True)
    processes = []
    try:
        processes.append(subprocess.Popen([sys.executable, str(ROOT / 'test/browser/board_server.py')], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, start_new_session=True))
        ready(f'http://127.0.0.1:{api}/')
        mode = 'preview' if os.getenv('BOARD_PRODUCTION') == '1' else 'dev'
        processes.append(subprocess.Popen(['npm', '--prefix', str(ROOT / 'web-react'), 'run', mode, '--', '--host', '127.0.0.1', '--port', str(web), '--strictPort'], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, start_new_session=True))
        ready(origin)
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as p:
            engine = os.getenv('BOARD_BROWSER', 'chromium')
            browser = p.webkit.launch(headless=True) if engine == 'webkit' else p.chromium.launch(channel='chrome', headless=True)
            mobile = dict(p.devices['iPhone 13']) if os.getenv('BOARD_MOBILE') == '1' else {}
            mobile.pop('default_browser_type', None)
            mobile['viewport'] = {'width': 1440, 'height': 1100}
            context = browser.new_context(**mobile, locale='zh-CN', timezone_id='America/Los_Angeles')
            context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
            context.route('https://fonts.gstatic.com/**', lambda route: route.abort())
            assert context.request.post(origin + '/api/auth/login', data={'username': 'board014', 'password': 'Board014-test'}).ok
            if os.getenv('BOARD_STALL_CACHE') == '1':
                context.add_init_script("Object.defineProperty(window, 'indexedDB', { configurable: true, value: { open: () => ({}) } });")
            page = context.new_page()
            page.clock.set_fixed_time(datetime(2026, 10, 27, 4, tzinfo=timezone.utc))
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            asset_responses = []
            def record_asset(response):
                if '/api/home/board/assets' in response.url:
                    asset_responses.append((response.request.method, response.status))
                    print('board asset HTTP', response.request.method, response.status, flush=True)
            page.on('response', record_asset)
            failed_uploads = []
            page.on('requestfailed', lambda request: failed_uploads.append(request.failure) if request.method == 'POST' and '/api/home/board/assets' in request.url else None)
            page.goto(origin + '/home')
            if os.getenv('BOARD_PRODUCTION') == '1':
                page.wait_for_function('navigator.serviceWorker.controller !== null')
                print('Production Service Worker controls the page', flush=True)
            expect(page.get_by_role('button', name='自定义', exact=True)).to_be_visible()
            page.get_by_role('button', name='留言板', exact=True).click()
            page.get_by_role('button', name='写便笺', exact=True).click()
            editor = page.get_by_role('dialog', name='写便笺', exact=True)
            expect(editor).to_be_visible()
            editor.get_by_label('便笺标题').fill('晚饭在冰箱里')
            editor.get_by_label('便笺正文 1').fill('今晚的饭在冰箱第二层，热一下就可以吃。\n' * 35)
            editor.get_by_label('小陈', exact=True).check()
            photo = BytesIO()
            real_photo = os.getenv('BOARD_TEST_IMAGE')
            if real_photo:
                photo.write(Path(real_photo).read_bytes())
                print('Real JPEG selected, bytes:', len(photo.getvalue()), flush=True)
            else:
                Image.new('RGB', (480, 320), '#c9bda3').save(photo, 'PNG')
            page.set_viewport_size({'width': 390, 'height': 844})
            editor.get_by_label('添加图片', exact=True).scroll_into_view_if_needed()
            page.screenshot(path=str(output / 'picker-mobile.png'))
            with page.expect_file_chooser(timeout=5000) as chooser:
                editor.get_by_label('添加图片', exact=True).click()
            if os.getenv('BOARD_PICKER_FOCUS') == '1':
                page.evaluate('window.dispatchEvent(new Event("focus"))')
                expect(editor.get_by_text('正在核实最新权限与状态…', exact=True)).to_be_visible()
                assert not editor.get_by_label('添加图片', exact=True).is_disabled(), 'Focus refresh disabled the pending file selection'
                expect(editor.get_by_text('正在核实最新权限与状态…', exact=True)).to_be_visible()
                print('Picker return: permission recheck active, native file input enabled', flush=True)
            chooser.value.set_files({'name': 'real-photo.jpg' if real_photo else 'dinner.png', 'mimeType': 'image/jpeg' if real_photo else 'image/png', 'buffer': photo.getvalue()})
            local_preview = editor.locator('.board-photo-previews img')
            expect(local_preview).to_have_js_property('complete', True)
            assert local_preview.evaluate('img => img.src.startsWith("blob:") && img.naturalWidth > 0')
            expect(editor.locator('.board-photo-previews').get_by_text(re.compile('正在处理图片|正在上传|等待服务器保存|已选中'))).to_be_visible()
            page.screenshot(path=str(output / 'local-photo-before-upload.png'))
            if os.getenv('BOARD_CANCEL_CHECK') == '1':
                expect(editor.get_by_text('已传输 100%，等待服务器保存…', exact=True)).to_be_visible()
                editor.get_by_role('button', name='取消上传', exact=True).click()
                expect(editor.get_by_text('已取消上传，图片尚未保存', exact=True)).to_be_visible()
                expect(editor.get_by_role('button', name='发布便笺', exact=True)).to_be_disabled()
                editor.get_by_role('button', name='重试上传', exact=True).click()
            expect(editor.get_by_role('button', name='发布便笺', exact=True)).to_be_enabled()
            expect(editor.get_by_text('图片已上传，发布便笺后生效', exact=True)).to_be_visible()
            print('Image size summary:', [value for value in editor.locator('.board-photo-grid figcaption span').all_text_contents() if '→' in value], flush=True)
            if os.getenv('BOARD_CANCEL_CHECK') == '1':
                assert failed_uploads, 'Cancel did not abort a network request'
                print('Actual XHR abort and retry verified', flush=True)
            editor.get_by_role('button', name='预览已保存图片 1', exact=True).click()
            image_dialog = page.get_by_role('dialog', name='图片预览', exact=True)
            expect(image_dialog.locator('img')).to_have_js_property('complete', True)
            assert image_dialog.locator('img').evaluate('img => img.naturalWidth > 0')
            image_dialog.get_by_role('button', name='返回', exact=True).click()

            page.set_viewport_size({'width': 1440, 'height': 1100})
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
            photo = note.locator('.board-image img')
            photo.scroll_into_view_if_needed()
            expect(photo).to_have_js_property('complete', True)
            assert photo.evaluate('img => img.naturalWidth > 0'), 'Published note image did not decode'
            if os.getenv('BOARD_MOBILE') == '1' and os.getenv('BOARD_IMAGE_ONLY') == '1':
                assert ('POST', 201) in asset_responses, 'No successful image upload request'
                # Reload the SW-controlled production page: no in-memory edits can supply the image.
                page.set_viewport_size({'width': 390, 'height': 844})
                page.reload()
                expect(note).to_be_visible()
                note.get_by_role('button', name='查看', exact=True).click()
                detail = page.get_by_role('dialog', name='便笺详情', exact=True)
                detail.get_by_role('button', name='查看便笺图片', exact=True).click()
                preview = page.get_by_role('dialog', name='便笺图片', exact=True).locator('img')
                expect(preview).to_have_js_property('complete', True)
                assert preview.evaluate('img => img.naturalWidth > 0')
                listing = context.request.get(origin + '/api/home/board/posts').json()['items']
                saved_asset = next(b['asset_id'] for b in listing[0]['post']['content_blocks'] if b['type'] == 'image')
                assert context.request.get(origin + '/api/home/board/assets/' + saved_asset).ok
                page.screenshot(path=str(output / 'real-photo-mobile-preview.png'))
                print('Real-photo mobile production/SW: native chooser, POST 201, persisted image after reload, GET 200 and decoded preview passed', flush=True)
                browser.close()
                return
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
            full_image = page.get_by_role('dialog', name='便笺图片', exact=True).locator('img')
            expect(full_image).to_have_js_property('complete', True)
            assert full_image.evaluate('img => img.naturalWidth > 0'), 'Image preview did not decode'
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
            if os.getenv('BOARD_IMAGE_ONLY') == '1':
                browser.close()
                return
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
