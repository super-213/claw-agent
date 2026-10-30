"""Calendar-only checks against the isolated home workbench server (no model calls)."""
from playwright.sync_api import sync_playwright, expect
from pathlib import Path
from datetime import datetime, timezone
import os
import re

out=Path(os.environ['HOME010_SCREENSHOTS'])
origin=os.environ['HOME010_WEB_ORIGIN']
with sync_playwright() as p:
 b=p.chromium.launch(channel='chrome',headless=True)
 c=b.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True,locale='zh-CN')
 c.route('https://fonts.googleapis.com/**',lambda route:route.abort())
 c.route('https://fonts.gstatic.com/**',lambda route:route.abort())
 c.request.post(origin+'/api/auth/login',data={'username':'home010','password':'Home010-test'})
 page=c.new_page();page.clock.set_fixed_time(datetime(2026,10,23,4,tzinfo=timezone.utc))
 errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 page.goto(origin+'/home');page.locator('.home-date-button').wait_for()
 d=page.get_by_role('dialog',name='家庭日历')
 # Drive real touch events, including the intermediate frame before release.
 touch=c.new_cdp_session(page)
 def finger(kind,x=None,y=340):
  touch.send('Input.dispatchTouchEvent',{'type':kind,'touchPoints':[] if x is None else [{'x':x,'y':y,'id':1}]})
 finger('touchStart',386);finger('touchMove',385,430);finger('touchEnd')
 expect(d).not_to_be_visible() # Vertical scrolling must not open the drawer.
 finger('touchStart',386);finger('touchMove',362);finger('touchMove',350)
 page.wait_for_timeout(150);finger('touchEnd')
 expect(page.locator('.home-calendar-drawer-backdrop')).to_be_hidden()
 finger('touchStart',386);finger('touchMove',350);finger('touchMove',210)
 offset=page.locator('.home-calendar-drawer').evaluate('(el) => new DOMMatrix(getComputedStyle(el).transform).m41')
 assert 0 < offset < 350, offset
 assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
 finger('touchEnd');expect(d).to_be_visible()
 expect(d.locator('.home-calendar-days button')).to_have_count(42)
 expect(d.get_by_role('button',name='回到今天',exact=True)).to_have_count(0)
 expect(d.get_by_label('所选日期的农历')).to_have_text('丙午年九月十四')
 d.get_by_role('button',name='2026-10-30',exact=True).click()
 expect(d.get_by_label('所选日期的农历')).to_have_text('丙午年九月廿一')
 page.wait_for_timeout(500)
 page.screenshot(path=str(out/'calendar-edge-drawer.png'))
 assert page.evaluate('document.body.style.overflow') == 'hidden'
 # Clicking inside keeps it open; the close button and outside scrim dismiss it.
 d.get_by_role('button',name='下个月',exact=True).click();expect(d).to_be_visible()
 d.get_by_role('button',name='关闭家庭日历',exact=True).click();expect(d).not_to_be_visible()
 page.locator('.home-date-button').click();expect(d).to_be_visible()
 page.mouse.click(10,340);expect(d).not_to_be_visible()
 page.locator('.home-date-button').click();expect(d).to_be_visible()
 page.keyboard.press('Escape');expect(d).not_to_be_visible()
 assert page.evaluate('document.body.style.overflow') != 'hidden'
 # Header can also be dragged right to close; content remains vertically scrollable.
 page.locator('.home-date-button').click();expect(d).to_be_visible();page.wait_for_timeout(500)
 finger('touchStart',90,32);finger('touchMove',150,32);finger('touchMove',340,32);finger('touchEnd')
 expect(d).not_to_be_visible()
 page.emulate_media(reduced_motion='reduce')
 finger('touchStart',386);finger('touchMove',350);finger('touchMove',190);finger('touchEnd')
 expect(d).to_be_visible();page.go_back();expect(d).not_to_be_visible()
 page.emulate_media(reduced_motion='no-preference')
 for width in [320,768,1199,1200]:
  page.set_viewport_size({'width':width,'height':844})
  assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
  if width < 1200:
   expect(page.locator('.home-calendar-edge')).to_be_visible()
   expect(page.locator('.home-schedule:not(.calendar-compact)')).to_be_hidden()
   finger('touchStart',width-4);finger('touchMove',width-40);finger('touchMove',width-180);finger('touchEnd')
   expect(d).to_be_visible()
   d.get_by_role('button',name='关闭家庭日历',exact=True).click();expect(d).not_to_be_visible()
  else:
   expect(page.locator('.home-calendar-edge')).to_be_hidden()
   expect(page.locator('.home-schedule:not(.calendar-compact)')).to_be_visible()
 page.set_viewport_size({'width':390,'height':844})
 page.locator('.home-date-button').click();expect(d).to_be_visible()
 d.get_by_role('button',name='查看选中日期全部日程',exact=True).click()
 expect(d).not_to_be_visible()
 expect(page).to_have_url(re.compile(r'/home/tasks\?'))
 print('calendar edge touch / tracking / scroll intent / dismissal / reduced motion / breakpoints passed',flush=True)
 assert not errors, errors
 b.close()
