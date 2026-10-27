"""Real desktop and mobile pointer acceptance for freely stacked paper notes."""
from pathlib import Path
import os
import signal
import subprocess
import sys
from validate_board import free_port, ready, ROOT


def main():
    api, web = free_port(), free_port()
    origin = f'http://127.0.0.1:{web}'
    env = {**os.environ, 'BOARD014_API_PORT': str(api), 'VITE_API_TARGET': f'http://127.0.0.1:{api}'}
    output = ROOT / '.data/validation/board-layout'
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
            context = browser.new_context(viewport={'width': 1440, 'height': 1100}, locale='zh-CN')
            context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
            context.route('https://fonts.gstatic.com/**', lambda route: route.abort())
            assert context.request.post(origin + '/api/auth/login', data={'username': 'board014', 'password': 'Board014-test'}).ok
            notes = [('晚饭在冰箱里', '今晚的饭在冰箱第二层，热一下就可以吃。\n' * 30), ('周末一起看照片', '照片都整理好了，周末一起选几张喜欢的。'), ('周六家庭聚餐', '周六晚上六点，一起吃饭。'), ('出门记得带钥匙', '备用钥匙在玄关抽屉里。')]
            for index, (title, body) in enumerate(notes):
                response = context.request.post(origin + '/api/home/board/posts', data={'request_id': f'layout-{index}', 'data': {'title': title, 'content_blocks': [{'type': 'text', 'text': body}], 'audience_mode': 'household', 'recipient_ids': []}})
                assert response.ok, response.text()
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(origin + '/home?panel=board')
            expect(page.locator('.board-canvas-note')).to_have_count(4)
            canvas = page.get_by_role('region', name='可自由摆放的留言板画布')
            canvas.scroll_into_view_if_needed()
            wrappers = page.locator('.board-canvas-note')
            first_id = wrappers.nth(0).get_attribute('data-note-id')
            second_id = wrappers.nth(1).get_attribute('data-note-id')
            first = page.locator(f'[data-note-id="{first_id}"]')
            second = page.locator(f'[data-note-id="{second_id}"]')

            def layout(identifier):
                return page.evaluate("id => { const key = Object.keys(localStorage).find(k => k.startsWith('claw.board.layout.v1.')); return JSON.parse(localStorage.getItem(key))[id]; }", identifier)

            def drag_to(wrapper, x, y):
                handle = wrapper.get_by_role('button', name='移动便笺：', exact=False)
                handle.scroll_into_view_if_needed()
                before = layout(wrapper.get_attribute('data-note-id'))
                box = handle.bounding_box()
                start_x, start_y = box['x'] + box['width'] / 2, box['y'] + box['height'] / 2
                page.mouse.move(start_x, start_y)
                page.mouse.down()
                scale = wrapper.bounding_box()['width'] / 280
                page.mouse.move(start_x + (x - before['x']) * scale, start_y + (y - before['y']) * scale, steps=8)
                page.mouse.up()

            drag_to(first, 84, 84)
            moved = layout(first_id)
            assert abs(moved['x'] - 84) < 2 and abs(moved['y'] - 84) < 2, moved
            expect(page.get_by_role('dialog')).to_have_count(0)
            drag_to(second, 100, 100)
            overlapped = layout(second_id)
            assert abs(overlapped['x'] - 100) < 2 and abs(overlapped['y'] - 100) < 2, overlapped
            assert overlapped['z'] > layout(first_id)['z']
            # Exposed paper edge brings the lower note to the front.
            first_box = first.bounding_box()
            page.mouse.click(first_box['x'] + 6, first_box['y'] + 10)
            assert layout(first_id)['z'] > layout(second_id)['z']
            expect(page.get_by_role('dialog')).to_have_count(0)
            first.get_by_role('button', name='移动便笺：', exact=False).press('ArrowRight')
            first.get_by_role('button', name='移动便笺：', exact=False).press('Shift+ArrowDown')
            adjusted = layout(first_id)
            assert abs(adjusted['x'] - 94) < 2 and abs(adjusted['y'] - 124) < 2
            page.reload()
            expect(page.locator('.board-canvas-note')).to_have_count(4)
            assert layout(first_id) == adjusted
            canvas.scroll_into_view_if_needed()
            print('drag, overlap, click-to-front, keyboard movement and reload persistence passed', flush=True)

            # Escape restores a drag rather than leaving a half-saved placement.
            handle = first.get_by_role('button', name='移动便笺：', exact=False)
            handle.scroll_into_view_if_needed()
            box = handle.bounding_box()
            page.mouse.move(box['x'] + 40, box['y'] + 20); page.mouse.down()
            page.mouse.move(box['x'] + 100, box['y'] + 70, steps=6)
            page.keyboard.press('Escape'); page.mouse.up()
            assert layout(first_id)['x'] == adjusted['x'] and layout(first_id)['y'] == adjusted['y']
            page.get_by_role('button', name='缩小画布', exact=True).click()
            assert float(page.get_by_label('画布缩放比例').inner_text().rstrip('%')) < 100
            drag_to(first, adjusted['x'] + 40, adjusted['y'] + 40)  # logical displacement is independent of the display zoom
            # A drag remains aligned with the pointer after zooming.
            zoomed = layout(first_id)
            assert abs(zoomed['x'] - (adjusted['x'] + 40)) < 3, zoomed
            # Zooming out must not leave an unreachable strip at the right.
            visible_board = canvas.bounding_box()
            actual_scale = first.bounding_box()['width'] / 280
            right_x = visible_board['width'] / actual_scale - 280 - 24
            drag_to(first, right_x, zoomed['y'])
            note_box = first.bounding_box()
            gap = visible_board['x'] + visible_board['width'] - note_box['x'] - note_box['width']
            assert 0 <= gap <= 24 * actual_scale + 3, (gap, actual_scale)
            assert abs(layout(first_id)['x'] - right_x) < 3
            drag_to(first, zoomed['x'], zoomed['y'])
            zoomed = layout(first_id)
            page.get_by_role('button', name='放大画布', exact=True).click()
            print('cancelled drag and zoom-correct pointer tracking passed', flush=True)

            page.get_by_role('button', name='完整显示留言板', exact=True).click()
            for screen_width, screen_height in [(1440, 900), (1366, 768), (1024, 768)]:
                page.set_viewport_size({'width': screen_width, 'height': screen_height})
                page.wait_for_function('''() => { const el = document.querySelector('.board-canvas-viewport'); return el && el.scrollHeight <= el.clientHeight + 1 && el.scrollWidth <= el.clientWidth + 1 && el.getBoundingClientRect().bottom < innerHeight; }''')
                assert page.locator('.home-command').bounding_box()['height'] <= 90
                assert page.evaluate('document.documentElement.scrollHeight <= innerHeight + 2')
                page.screenshot(path=str(output / f'bounded-desktop-{screen_width}-{screen_height}.png'), full_page=True, animations='disabled')
            page.set_viewport_size({'width': 1440, 'height': 1100})
            print('compact assistant and viewport-bounded board without page/canvas overflow passed at three desktop sizes', flush=True)

            for theme in ['light', 'dark']:
                page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                page.screenshot(path=str(output / f'canvas-{theme}-1440.png'), full_page=True, animations='disabled')
                page.set_viewport_size({'width': 390, 'height': 844})
                expect(page.locator('.board-note-compact')).to_have_count(4)
                expect(page.get_by_role('button', name='总览', exact=True)).to_have_count(0)
                expect(page.get_by_role('button', name='画布', exact=True)).to_have_count(0)
                expect(page.locator('.board-canvas-viewport')).to_have_count(0)
                compact = page.locator('.board-note-compact')
                assert compact.nth(0).bounding_box()['width'] < 180
                assert abs(compact.nth(0).bounding_box()['height'] - 210) < 1
                assert abs(compact.nth(0).bounding_box()['y'] - compact.nth(1).bounding_box()['y']) < 1
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(output / f'overview-{theme}-390.png'), full_page=True, animations='disabled')
                compact.nth(0).get_by_role('button', name='查看', exact=True).click()
                detail = page.get_by_role('dialog', name='便笺详情', exact=True)
                expect(detail).to_be_visible()
                detail.get_by_role('button', name='返回', exact=True).click()
                assert layout(first_id) == zoomed
                page.set_viewport_size({'width': 1440, 'height': 1100})
                expect(page.locator('.board-canvas-note')).to_have_count(4)
            print('phone overview only, full detail, themes and preserved desktop positions passed', flush=True)

            # Touch devices keep the overview in portrait and landscape.
            touch = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, device_scale_factor=1)
            assert touch.request.post(origin + '/api/auth/login', data={'username': 'board014', 'password': 'Board014-test'}).ok
            phone = touch.new_page()
            phone.goto(origin + '/home?panel=board')
            for phone_width, phone_height in [(390, 844), (844, 390)]:
                phone.set_viewport_size({'width': phone_width, 'height': phone_height})
                expect(phone.locator('.board-note-compact')).to_have_count(4)
                expect(phone.locator('.board-canvas-viewport')).to_have_count(0)
                expect(phone.get_by_role('button', name='画布', exact=True)).to_have_count(0)
                phone.locator('.board-note-compact').nth(0).get_by_role('button', name='查看', exact=True).tap()
                expect(phone.get_by_role('dialog', name='便笺详情', exact=True)).to_be_visible()
                phone.get_by_role('dialog', name='便笺详情', exact=True).get_by_role('button', name='返回', exact=True).tap()
            assert not page.locator('.board-layout-hint').count()
            assert not page.locator('.board-layout-caption').count()
            assert not errors, errors
            print('no helper text, right-edge placement and touch-only overview in both phone orientations passed', flush=True)
            browser.close()
    finally:
        for process in reversed(processes):
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)


if __name__ == '__main__': main()
