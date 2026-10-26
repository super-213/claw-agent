"""Run against home_workbench_server.py and Vite with isolated example data.

HOME010_WEB_ORIGIN and HOME010_SCREENSHOTS select the local server and output.
"""
import os
from pathlib import Path
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright

origin = os.environ['HOME010_WEB_ORIGIN']
out = Path(os.environ['HOME010_SCREENSHOTS'])
out.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome', headless=True)
    context = browser.new_context(viewport={'width': 1440, 'height': 900}, locale='zh-CN')
    # Keep layout checks independent of external font service availability.
    context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
    context.route('https://fonts.gstatic.com/**', lambda route: route.abort())
    response = context.request.post(origin + '/api/auth/login', data={
        'username': 'home010', 'password': 'Home010-test',
    })
    assert response.ok, response.text()
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(origin + '/home')
    nav = page.get_by_role('navigation', name='主导航', exact=True)
    expect(nav.get_by_role('link')).to_have_text(['工作台', '对话', '家庭', '更多'])
    nav.get_by_role('link', name='家庭', exact=True).click()
    expect(page.get_by_role('heading', name='家庭', exact=True)).to_be_visible()
    categories = page.get_by_role('navigation', name='家庭信息分类')
    expect(categories.get_by_role('link', name='事项')).to_have_attribute('aria-current', 'page')
    categories.get_by_role('link', name='物品').click()
    expect(page.get_by_role('heading', name='家庭物品')).to_be_visible()
    nav.get_by_role('link', name='工作台', exact=True).click()
    nav.get_by_role('link', name='家庭', exact=True).click()
    expect(page.get_by_role('heading', name='家庭物品')).to_be_visible()
    page.goto(origin + '/home/family')
    expect(categories.get_by_role('link', name='物品')).to_have_attribute('aria-current', 'page')
    page.get_by_role('button', name='添加', exact=True).click()
    chooser = page.get_by_role('dialog', name='添加家庭记录')
    expect(chooser).to_be_visible()
    chooser.get_by_role('button', name='新建事项', exact=False).click()
    expect(page.get_by_role('dialog', name='记录事项')).to_be_visible()
    page.keyboard.press('Escape')
    expect(page.get_by_role('dialog')).to_have_count(0)
    categories.get_by_role('link', name='物品').click()
    page.get_by_role('button', name='药箱', exact=True).click()
    page.get_by_role('button', name='添加', exact=True).click()
    chooser.get_by_role('button', name='添加物品', exact=False).click()
    expect(page.get_by_role('dialog', name='添加物品')).to_be_visible()
    expect(page.get_by_role('dialog', name='添加物品').get_by_text('药箱 · 家庭共享')).to_be_visible()
    page.keyboard.press('Escape')
    expect(page.get_by_role('dialog')).to_have_count(0)
    print('Family navigation, remembered category, and both add flows passed', flush=True)

    nav.get_by_role('link', name='对话', exact=True).click()
    expect(page.locator('.composer-input')).to_be_enabled()
    expect(nav.get_by_role('link', name='对话', exact=True)).to_have_attribute('aria-current', 'page')
    page.locator('.composer-input').fill('示例·保留这份未发送的草稿')
    nav.get_by_role('link', name='工作台', exact=True).click()
    page.get_by_label('和家庭 Agent 对话').fill('示例·工作台草稿')
    nav.get_by_role('link', name='对话', exact=True).click()
    expect(page.locator('.composer-input')).to_have_value('示例·保留这份未发送的草稿')
    nav.get_by_role('link', name='工作台', exact=True).click()
    expect(page.get_by_label('和家庭 Agent 对话')).to_have_value('示例·工作台草稿')
    sent = []
    page.on('request', lambda request: sent.append(request.url)
            if request.method == 'POST' and '/chat' in request.url else None)
    sent_text = '示例·帮我记录一条日程 ' + uuid4().hex[:8]
    page.get_by_label('和家庭 Agent 对话').fill(sent_text)
    page.get_by_role('button', name='发送', exact=True).click()
    expect(page.locator('.message.user').filter(has_text=sent_text)).to_have_count(1)
    expect(page.get_by_text('示例日程已记录。', exact=True).first).to_be_visible(timeout=15000)
    assert len(sent) == 1, sent
    print('Chat draft restoration and single workbench send passed', flush=True)

    for width, height in [(375, 812), (390, 844), (768, 1024), (1024, 900), (1440, 900)]:
        page.set_viewport_size({'width': width, 'height': height})
        nav = page.get_by_role('navigation', name='手机主导航' if width < 768 else '主导航', exact=True)
        expect(nav.get_by_role('link', name='对话', exact=True)).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
        composer = page.locator('.composer-input').bounding_box()
        assert composer['height'] < 120, (width, composer)
        if width < 768:
            assert composer['y'] + composer['height'] < page.locator('.home-bottom-nav').bounding_box()['y']
        nav.get_by_role('link', name='家庭', exact=True).click()
        categories.get_by_role('link', name='物品').click()
        expect(page.get_by_role('heading', name='家庭物品')).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
        page.screenshot(path=str(out / f'family-{width}.png'), full_page=True)
        nav.get_by_role('link', name='对话', exact=True).click()
        expect(page.locator('.composer-input')).to_be_enabled()
        page.screenshot(path=str(out / f'chat-{width}.png'))
    page.emulate_media(color_scheme='dark', reduced_motion='reduce')
    page.screenshot(path=str(out / 'chat-dark.png'))
    assert not errors, errors
    print('Five viewport widths, dark mode, and no browser runtime errors passed', flush=True)
    browser.close()
