"""Account/settings acceptance with real HTTP and isolated synthetic accounts."""
import os
import re
import signal
import subprocess
import sys
from validate_board import free_port, ready, ROOT


def main():
    api, web = free_port(), free_port()
    origin = f'http://127.0.0.1:{web}'
    env = {**os.environ, 'BOARD014_API_PORT': str(api), 'VITE_API_TARGET': f'http://127.0.0.1:{api}'}
    output = ROOT / '.data/validation/account-settings'
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
            context = browser.new_context(locale='zh-CN', reduced_motion='reduce')
            context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
            context.route('https://fonts.gstatic.com/**', lambda route: route.abort())
            assert context.request.post(origin + '/api/auth/login', data={'username': 'board014', 'password': 'Board014-test', 'remember_me': True}).ok
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            for theme in ['light', 'dark']:
                page.goto(origin + '/home/more')
                page.evaluate('(theme) => localStorage.setItem("claw-theme", theme)', theme)
                page.reload()
                for width in [375, 768, 1440]:
                    page.set_viewport_size({'width': width, 'height': 1000})
                    expect(page.get_by_role('link', name=re.compile('账号.*个人资料'))).to_be_visible()
                    page.get_by_role('link', name=re.compile('账号.*个人资料')).click()
                    expect(page.get_by_role('heading', name='账号', exact=True)).to_be_visible()
                    expect(page.get_by_role('group', name='外观')).to_have_count(0)
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.screenshot(path=str(output / f'account-{theme}-{width}.png'), full_page=True)
                    page.get_by_role('button', name=re.compile('修改密码')).click()
                    expect(page.get_by_label('当前密码', exact=True)).to_be_focused()
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.get_by_role('button', name='取消', exact=True).click()
                    page.get_by_role('link', name='返回更多').click()
                    page.get_by_role('link', name=re.compile('设置.*外观与回复通知')).click()
                    expect(page.get_by_role('group', name='外观')).to_be_visible()
                    expect(page.get_by_role('button', name='退出登录')).to_have_count(0)
                    expect(page.get_by_role('button', name=re.compile('模型与设备'))).to_be_visible()
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.screenshot(path=str(output / f'settings-{theme}-{width}.png'), full_page=True)
                    page.get_by_role('link', name='返回更多').click()
            page.goto(origin + '/home/more?section=account')
            page.get_by_role('button', name='修改显示名称').click()
            page.get_by_role('textbox', name='显示名称', exact=True).fill('小林的新称呼')
            page.get_by_role('button', name='保存名称').click()
            expect(page.get_by_role('status')).to_contain_text('显示名称已更新')
            page.reload()
            expect(page.locator('.account-info-row').first).to_contain_text('小林的新称呼')
            members = context.request.get(origin + '/api/home/members')
            assert members.ok, members.text()
            assert members.json()['members'][0]['display_name'] == '小林'
            page.get_by_role('button', name=re.compile('通行密钥')).click()
            expect(page.get_by_text('通行密钥暂未启用，你仍可使用密码登录。')).to_be_visible()
            page.get_by_role('button', name=re.compile('修改密码')).click()
            page.get_by_label('当前密码', exact=True).fill('wrong-password')
            page.get_by_label('新密码', exact=True).fill('Account-settings-new')
            page.get_by_label('确认新密码', exact=True).fill('Account-settings-new')
            page.get_by_role('button', name='保存并重新登录').click()
            expect(page.get_by_role('alert')).to_contain_text('当前密码不正确')
            page.get_by_label('当前密码', exact=True).fill('Board014-test')
            page.get_by_role('button', name='保存并重新登录').click()
            page.wait_for_url('**/login')
            assert context.request.get(origin + '/api/auth/me').status == 401
            assert context.request.post(origin + '/api/auth/login', data={'username': 'board014', 'password': 'Board014-test'}).status == 401
            assert context.request.post(origin + '/api/auth/login', data={'username': 'board014', 'password': 'Account-settings-new'}).ok
            regular = browser.new_context(locale='zh-CN')
            assert regular.request.post(origin + '/api/auth/login', data={'username': 'board014b', 'password': 'Board014-test'}).ok
            regular_page = regular.new_page()
            regular_page.goto(origin + '/home/more?section=settings')
            expect(regular_page.get_by_role('group', name='外观')).to_be_visible()
            expect(regular_page.get_by_text('管理员设置')).to_have_count(0)
            assert not errors, errors
            browser.close()
        print('PASS: 375/768/1440, light/dark, navigation, profile persistence, family name isolation, password rejection/change/login and administrator visibility. No real model calls or production data writes.')
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=10)


if __name__ == '__main__':
    main()
