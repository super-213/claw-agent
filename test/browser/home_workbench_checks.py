"""Requires a dedicated server and Vite preview from validate_home_workbench.py."""
from playwright.sync_api import sync_playwright, expect
from pathlib import Path
import os
from datetime import datetime, timezone
out=Path(os.environ['HOME010_SCREENSHOTS'])
origin=os.environ['HOME010_WEB_ORIGIN']
with sync_playwright() as p:
 b=p.chromium.launch(channel='chrome',headless=True)
 c=b.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True,locale='zh-CN',timezone_id='America/Los_Angeles')
 # Local layout checks must not depend on external font availability.
 c.route('https://fonts.googleapis.com/**',lambda route:route.abort())
 c.route('https://fonts.gstatic.com/**',lambda route:route.abort())
 c.request.post(origin+'/api/auth/login',data={'username':'home010','password':'Home010-test'})
 page=c.new_page();page.clock.set_fixed_time(datetime(2026,10,23,4,tzinfo=timezone.utc));errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 page.goto(origin+'/home');page.locator('.home-attention-row').first.wait_for()
 page.screenshot(path=str(out/'mobile-initial.png'),full_page=True)
 # Directly complete a due task.
 row=page.locator('.home-attention-row').filter(has_text='示例·取快递')
 row.get_by_role('button',name='完成',exact=True).click()
 expect(page.get_by_role('status').filter(has_text='已完成：')).to_be_visible()
 expect(row).to_have_count(0)
 print('complete passed',flush=True)
 # Memo form, explicit visibility and browser Back.
 page.get_by_role('button',name='记录事项',exact=True).click()
 dialog=page.get_by_role('dialog',name='记录事项');expect(dialog).to_be_visible()
 dialog.get_by_label('事项内容').fill('示例·手机记录的家庭备忘')
 dialog.get_by_label('可见范围').select_option('household')
 dialog.get_by_role('button',name='保存事项',exact=True).click()
 expect(dialog).not_to_be_visible()
 expect(page.get_by_role('button',name='示例·手机记录的家庭备忘',exact=True)).to_be_visible()
 print('memo passed',flush=True)
 page.get_by_role('button',name='示例·手机记录的家庭备忘',exact=True).click()
 expect(page.get_by_role('dialog',name='事项详情')).to_be_visible()
 page.go_back();expect(page.get_by_role('dialog')).to_have_count(0)
 print('detail back passed',flush=True)
 # Expiring item, actual medicine location.
 page.locator('.home-bottom-nav').get_by_role('link',name='家庭',exact=True).click()
 page.get_by_role('navigation',name='家庭信息分类').get_by_role('link',name='物品',exact=True).click()
 page.get_by_role('button',name='药箱',exact=True).click()
 page.get_by_role('button',name='添加',exact=True).click()
 page.get_by_role('dialog',name='添加家庭记录').get_by_role('button',name='添加物品',exact=False).click()
 d=page.get_by_role('dialog',name='添加物品');expect(d).to_be_visible()
 d.get_by_label('名称',exact=True).fill('示例·手机添加的药品')
 d.get_by_label('数量',exact=True).fill('2')
 d.get_by_text('更多选项：到期日期与存放位置',exact=True).click()
 d.get_by_label('到期日期',exact=True).fill('2026-10-25')
 d.get_by_role('button',name='保存物品').click()
 expect(d).not_to_be_visible()
 expect(page.get_by_role('button',name='示例·手机添加的药品 2个',exact=False)).to_be_visible()
 print('inventory save passed',flush=True)
 # Filter -> detail -> Back: filter remains.
 page.get_by_role('button',name='筛选',exact=True).click()
 d=page.get_by_role('dialog',name='筛选物品')
 d.get_by_label('物品状态').select_option('expiring')
 d.get_by_role('button',name='应用',exact=True).click();expect(d).not_to_be_visible()
 page.get_by_role('button',name='示例·手机添加的药品 2个',exact=False).click()
 d=page.get_by_role('dialog',name='物品详情');expect(d).to_be_visible()
 page.screenshot(path=str(out/'mobile-inventory-detail.png'),full_page=True)
 page.go_back();expect(d).not_to_be_visible()
 expect(page.get_by_text('已过期与三天内到期 · 2 项',exact=True)).to_be_visible()
 print('filter detail return passed',flush=True)
 # The primary conversation entry is available without typing first.
 page.locator('.home-bottom-nav').get_by_role('link',name='对话',exact=True).click()
 expect(page.locator('.composer-input')).to_be_enabled()
 page.locator('.composer-input').fill('示例·尚未发送的草稿')
 page.screenshot(path=str(out/'mobile-chat.png'),full_page=True)
 page.locator('.home-bottom-nav').get_by_role('link',name='工作台',exact=True).click()
 page.locator('.home-bottom-nav').get_by_role('link',name='对话',exact=True).click()
 expect(page.locator('.composer-input')).to_have_value('示例·尚未发送的草稿')
 assert not errors,errors
 print('primary chat entry and retained draft passed',flush=True)
 b.close()

from playwright.sync_api import sync_playwright, expect
from pathlib import Path
out=Path(os.environ['HOME010_SCREENSHOTS'])
origin=os.environ['HOME010_WEB_ORIGIN']
with sync_playwright() as p:
 b=p.chromium.launch(channel='chrome',headless=True)
 c=b.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True,locale='zh-CN')
 # Local layout checks must not depend on external font availability.
 c.route('https://fonts.googleapis.com/**',lambda route:route.abort())
 c.route('https://fonts.gstatic.com/**',lambda route:route.abort())
 c.request.post(origin+'/api/auth/login',data={'username':'home010','password':'Home010-test'})
 page=c.new_page();page.clock.set_fixed_time(datetime(2026,10,23,4,tzinfo=timezone.utc));errs=[];page.on('pageerror',lambda e:errs.append(str(e)))
 page.goto(origin+'/home');page.locator('.home-attention-row').first.wait_for()
 before=c.request.get(origin+'/api/home/tasks?view=visible&status=open').json()['total']
 page.get_by_label('和家庭 Agent 对话').fill('/ 日程 今天新增示例')
 page.get_by_role('button',name='发送',exact=True).click()
 d=page.locator('.chat-workspace');expect(d).to_be_visible()
 assert d.locator('.composer').evaluate('(e)=>getComputedStyle(e).backgroundColor')=='rgb(199, 233, 255)'
 assert d.locator('textarea').bounding_box()['height'] < 100
 expect(d.get_by_text('示例日程已记录。',exact=True).first).to_be_visible(timeout=15000)
 page.wait_for_timeout(300);page.screenshot(path=str(out/'mobile-chat-complete.png'))
 page.locator('.home-bottom-nav').get_by_role('link',name='工作台',exact=True).click();expect(d).not_to_be_visible()
 page.get_by_role('button',name='查看全部',exact=True).click()
 expect(page.locator('.home-attention-row').filter(has_text='示例·聊天新增日程').first).to_be_visible()
 after=c.request.get(origin+'/api/home/tasks?view=visible&status=open').json()['total']
 assert after==before+1,(before,after)
 print('chat native tool -> returned home refresh passed',flush=True)
 page.wait_for_timeout(200);page.screenshot(path=str(out/'mobile-after-chat.png'),full_page=True)
 print('errors',errs,flush=True)
 # All core widths + dark + text zoom use actual page content.
 page.goto(origin+'/home');page.locator('.home-attention-row').first.wait_for()
 for w,h in [(375,812),(390,844),(768,1024),(1024,900),(1440,900)]:
  page.set_viewport_size({'width':w,'height':h});page.wait_for_timeout(250)
  assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),w
  page.screenshot(path=str(out/f'final-home-{w}.png'),full_page=True)
  if w==1440:
   rect=page.locator('.home-command input').bounding_box();assert rect['y']+rect['height'] < h,rect
  print('viewport',w,'passed',flush=True)
 page.emulate_media(color_scheme='dark',reduced_motion='reduce');page.wait_for_timeout(200)
 page.screenshot(path=str(out/'final-dark-desktop.png'),full_page=True)
 page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(300);page.evaluate('window.scrollTo(0,0)');page.screenshot(path=str(out/'final-dark-mobile.png'))
 page.evaluate("const sizes=[...document.querySelectorAll('.home-shell *')].map(el=>[el,parseFloat(getComputedStyle(el).fontSize)]);sizes.forEach(([el,size])=>el.style.fontSize=(size*2)+'px')")
 assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
 page.screenshot(path=str(out/'mobile-text-200.png'),full_page=True)
 print('dark/reduced motion/200% text passed',flush=True)
 b.close()

# Reference-layout regression: AI first, borderless rails, real month navigation,
# and persisted widget editing using an actual pointer gesture.
with sync_playwright() as p:
 b=p.chromium.launch(channel='chrome',headless=True)
 c=b.new_context(viewport={'width':1440,'height':900},locale='zh-CN',timezone_id='America/Los_Angeles')
 # Local layout checks must not depend on external font availability.
 c.route('https://fonts.googleapis.com/**',lambda route:route.abort())
 c.route('https://fonts.gstatic.com/**',lambda route:route.abort())
 c.request.post(origin+'/api/auth/login',data={'username':'home010','password':'Home010-test'})
 page=c.new_page();page.clock.set_fixed_time(datetime(2026,10,23,4,tzinfo=timezone.utc));page.goto(origin+'/home')
 expect(page.locator('.home-calendar-days button')).to_have_count(42)
 expect(page.locator('.home-widget-grid > article')).to_have_count(6)
 page.wait_for_timeout(250)
 assert page.locator('.home-command').bounding_box()['y'] < page.locator('.home-widget-grid').bounding_box()['y']
 assert page.locator('.home-command input').bounding_box()['y'] < 300
 assert page.locator('.home-app').bounding_box()['x'] <= 12
 assert page.locator('.home-schedule').evaluate("e=>getComputedStyle(e).borderTopWidth")=='0px'
 assert page.locator('.home-brand svg').evaluate("e=>getComputedStyle(e).borderTopWidth")=='0px'
 page.screenshot(path=str(out/'reference-desktop.png'),full_page=True)
 calendar=page.locator('.home-schedule')
 calendar.get_by_role('button',name='下个月',exact=True).click()
 expect(calendar.get_by_role('heading',name='2026 年 11 月',exact=True)).to_be_visible()
 calendar.get_by_role('button',name='回到今天',exact=True).click()
 expect(calendar.get_by_role('button',name='2026-10-23',exact=True)).to_have_attribute('aria-pressed','true')
 calendar.get_by_role('button',name='2026-10-24',exact=True).click()
 expect(calendar.get_by_role('button',name='2026-10-24',exact=True)).to_have_attribute('aria-pressed','true')
 calendar.get_by_role('button',name='回到今天',exact=True).click()
 page.get_by_role('button',name='自定义',exact=True).click()
 start=page.get_by_role('button',name='移动今日日程，使用方向键排序').bounding_box()
 target=page.locator('[data-widget-kind="fridge"]').bounding_box()
 page.mouse.move(start['x']+start['width']/2,start['y']+start['height']/2)
 page.mouse.down();page.mouse.move(target['x']+target['width']/2,target['y']+80,steps=12);page.mouse.up()
 expect(page.locator('.home-widget-grid > article').first).to_have_attribute('data-widget-kind','fridge')
 page.get_by_label('冰箱尺寸',exact=True).select_option('medium')
 page.get_by_role('button',name='移除药箱',exact=True).click()
 page.reload();expect(page.locator('[data-widget-kind="medicine"]')).to_have_count(0)
 expect(page.locator('[data-widget-kind="fridge"]')).to_have_class('home-widget widget-fridge widget-medium')
 page.get_by_role('button',name='自定义',exact=True).click()
 page.get_by_role('button',name='添加组件',exact=True).click()
 d=page.get_by_role('dialog',name='添加小组件')
 d.get_by_role('button',name='药箱 添加 +',exact=True).click()
 page.go_back();expect(d).not_to_be_visible()
 expect(page.locator('[data-widget-kind="medicine"]')).to_have_count(1)
 page.screenshot(path=str(out/'reference-widget-edit.png'),full_page=True)
 page.get_by_role('button',name='恢复默认',exact=True).click()
 page.locator('.home-widget-heading').get_by_role('button',name='完成',exact=True).click()
 # Presets reset the task view so calendar filters cannot leak into memo shortcuts.
 calendar.get_by_role('button',name='查看选中日期全部日程',exact=True).click()
 expect(page.get_by_text('日期：2026-10-23',exact=False)).to_be_visible()
 page.locator('.home-side-nav').get_by_role('link',name='工作台',exact=True).click()
 page.locator('[data-widget-kind="memos"]').get_by_role('button').click()
 expect(page.get_by_role('button',name='备忘',exact=True)).to_have_attribute('aria-pressed','true')
 expect(page.get_by_role('button',name='示例·买一把新的厨房剪刀',exact=True)).to_be_visible()
 page.locator('.home-side-nav').get_by_role('link',name='工作台',exact=True).click()
 # Narrow screens retain AI first and expose the same calendar from the date.
 page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(200)
 page.locator('.home-date-button').click()
 d=page.get_by_role('dialog',name='家庭日历');expect(d).to_be_visible()
 expect(d.locator('.home-calendar-days button')).to_have_count(42)
 page.wait_for_timeout(250);page.screenshot(path=str(out/'reference-mobile-calendar.png'))
 page.go_back();expect(d).not_to_be_visible()
 assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
 page.wait_for_timeout(200);page.screenshot(path=str(out/'reference-mobile.png'),full_page=True)
 page.emulate_media(color_scheme='dark',reduced_motion='reduce');page.wait_for_timeout(200)
 page.screenshot(path=str(out/'reference-dark-mobile.png'),full_page=True)
 page.set_viewport_size({'width':1440,'height':900});page.wait_for_timeout(200)
 page.screenshot(path=str(out/'reference-dark-desktop.png'),full_page=True)
 print('reference layout / calendar / pointer reorder / per-account saved widgets passed',flush=True)
 b.close()

with sync_playwright() as p:
 b=p.chromium.launch(channel='chrome',headless=True)
 c=b.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True,locale='zh-CN')
 # Local layout checks must not depend on external font availability.
 c.route('https://fonts.googleapis.com/**',lambda route:route.abort())
 c.route('https://fonts.gstatic.com/**',lambda route:route.abort())
 c.request.post(origin+'/api/auth/login',data={'username':'home010','password':'Home010-test'})
 page=c.new_page();page.clock.set_fixed_time(datetime(2026,10,23,4,tzinfo=timezone.utc));page.goto(origin+'/home')
 page.get_by_role('button',name='自定义',exact=True).click()
 start=page.get_by_role('button',name='移动今日日程，使用方向键排序').bounding_box()
 target=page.locator('[data-widget-kind="fridge"]').bounding_box()
 sx,sy=start['x']+start['width']/2,start['y']+start['height']/2
 tx,ty=target['x']+target['width']/2,target['y']+100
 cdp=c.new_cdp_session(page)
 cdp.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':sx,'y':sy}]})
 for step in range(1,13):
  cdp.send('Input.dispatchTouchEvent',{'type':'touchMove','touchPoints':[{'x':sx+(tx-sx)*step/12,'y':sy+(ty-sy)*step/12}]})
 cdp.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
 expect(page.locator('.home-widget-grid > article').first).to_have_attribute('data-widget-kind','fridge')
 page.screenshot(path=str(out/'reference-touch-widget-edit.png'))
 print('mobile touch drag passed',flush=True)
 b.close()

# The standalone and home chat share the same reading surfaces and controls.
with sync_playwright() as p:
 b=p.chromium.launch(channel='chrome',headless=True)
 c=b.new_context(viewport={'width':1440,'height':960},locale='zh-CN')
 # Local layout checks must not depend on external font availability.
 c.route('https://fonts.googleapis.com/**',lambda route:route.abort())
 c.route('https://fonts.gstatic.com/**',lambda route:route.abort())
 c.request.post(origin+'/api/auth/login',data={'username':'home010','password':'Home010-test'})
 page=c.new_page();page.clock.set_fixed_time(datetime(2026,10,23,4,tzinfo=timezone.utc));errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
 page.goto(origin+'/chat')
 page.get_by_role('button',name='周末的家庭安排',exact=False).click()
 expect(page.locator('.message.final').get_by_text('周末准备清单',exact=True)).to_be_visible()
 assert page.locator('.workspace-summary').count()==0
 assert page.locator('.current-context').count()==0
 assert page.locator('.tool-execution-details').first.evaluate('(e)=>!e.open')
 expect(page.locator('.tool-call-output').first).not_to_be_visible()
 assert page.locator('.composer-input').bounding_box()['y'] < 960
 assert page.locator('.brand-icon').evaluate('(e)=>getComputedStyle(e).borderTopWidth')=='0px'
 assert page.locator('.chat-workspace').evaluate('(e)=>getComputedStyle(e).gridTemplateColumns.split(" ").slice(0,2)')==['76px','252px']
 assert page.locator('.req-tag').first.evaluate('(e)=>getComputedStyle(e).backgroundColor')=='rgba(0, 0, 0, 0)'
 assert page.locator('.composer').evaluate('(e)=>getComputedStyle(e).backgroundColor')=='rgb(199, 233, 255)'
 page.get_by_label('会话详情',exact=True).click()
 expect(page.get_by_text('会话详情',exact=True)).to_be_visible()
 page.get_by_label('会话详情',exact=True).click()
 page.locator('.tool-execution-details > summary').first.click()
 expect(page.locator('.tool-call-output').first).to_be_visible()
 page.locator('.tool-execution-details > summary').first.click()
 page.locator('.composer-input').fill('把周六的采购安排在上午十点')
 page.wait_for_timeout(250);page.screenshot(path=str(out/'chat-desktop.png'))
 page.emulate_media(color_scheme='dark',reduced_motion='reduce');page.wait_for_timeout(200)
 assert page.locator('.composer').evaluate('(e)=>getComputedStyle(e).backgroundColor')=='rgb(33, 62, 80)'
 page.screenshot(path=str(out/'chat-dark-desktop.png'))
 page.emulate_media(color_scheme='light')
 for width in [375,390,768,1024]:
  page.set_viewport_size({'width':width,'height':844});page.wait_for_timeout(150)
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
  assert page.locator('.composer-input').bounding_box()['y'] < 844,width
  assert page.locator('.send-btn').bounding_box()['x']+page.locator('.send-btn').bounding_box()['width']<=width,width
  if width==390:
   page.screenshot(path=str(out/'chat-mobile.png'))
   trigger=page.get_by_role('button',name='打开历史对话',exact=True);trigger.click()
   sidebar=page.get_by_role('dialog',name='历史对话',exact=True)
   expect(sidebar).to_be_visible()
   for _ in range(20):page.keyboard.press('Tab')
   assert sidebar.evaluate('(e)=>e.contains(document.activeElement)')
   page.screenshot(path=str(out/'chat-mobile-history.png'))
   page.keyboard.press('Escape');expect(sidebar).not_to_be_visible()
   expect(trigger).to_be_focused()
   assert page.locator('.sidebar-layer').evaluate('(e)=>e.inert')
   trigger.click();page.locator('.sidebar-backdrop').click(position={'x':380,'y':600})
   expect(page.get_by_role('dialog',name='历史对话',exact=True)).not_to_be_visible()
 page.set_viewport_size({'width':390,'height':480});page.wait_for_timeout(150)
 assert page.locator('.send-btn').bounding_box()['y']+44<=480
 page.set_viewport_size({'width':390,'height':844})
 page.evaluate("const sizes=[...document.querySelectorAll('.chat-workspace *')].map(el=>[el,parseFloat(getComputedStyle(el).fontSize)]);sizes.forEach(([el,size])=>el.style.fontSize=(size*2)+'px')")
 assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
 assert page.locator('.send-btn').bounding_box()['x']+44<=390
 page.screenshot(path=str(out/'chat-mobile-text-200.png'))
 assert not errors,errors
 print('shared chat style / disclosures / responsive composer / mobile keyboard and backdrop passed',flush=True)
 b.close()
