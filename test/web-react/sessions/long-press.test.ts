import React, { useState } from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { SessionSidebar } from '../../../web-react/src/features/sessions/SessionSidebar';

let mobile = true;
const openSession = vi.fn();
const copySession = vi.fn();
const shareSession = vi.fn();
const deleteSession = vi.fn();
const toggleMenu = vi.fn();
function Harness({ owner = 'me', open = true }: { owner?: string; open?: boolean }) {
  const [menu, setMenu] = useState<string | null>(null);
  return React.createElement(SessionSidebar, {
    open, collapsed: false,
    sessions: [{ id: 'one', title: '测试会话', owner_user_id: owner }],
    currentSessionId: null,
    currentUser: { id: 'me', username: 'test', role: 'user', status: 'active' },
    busySessionIds: new Set<string>(), menuSessionId: menu,
    onCloseMobile: vi.fn(), onCreateSession: vi.fn(), onOpenSession: openSession,
    onToggleSessionMenu: (id) => { toggleMenu(id); setMenu(id); },
    onCopySession: copySession, onShareSession: shareSession, onDeleteSession: deleteSession,
  });
}
const row = () => screen.getByRole('button', { name: '测试会话' });
function pointer(type: string, extra: Record<string, unknown> = {}) {
  const event = new Event(type, { bubbles: true, cancelable: true });
  Object.entries({ pointerType: 'touch', pointerId: 1, isPrimary: true, clientX: 30, clientY: 40, ...extra })
    .forEach(([key, value]) => Object.defineProperty(event, key, { value }));
  fireEvent(row(), event);
}
const hold = () => act(() => { vi.advanceTimersByTime(500); });
beforeEach(() => {
  mobile = true;
  vi.useFakeTimers();
  window.matchMedia = vi.fn().mockImplementation(() => ({
    matches: mobile, addEventListener: vi.fn(), removeEventListener: vi.fn(),
  }));
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.clearAllMocks(); });

it('opens all three existing actions after a touch hold and consumes the release click', () => {
  render(React.createElement(Harness));
  pointer('pointerdown');
  act(() => { vi.advanceTimersByTime(499); });
  expect(screen.queryByRole('button', { name: '复制会话' })).toBeNull();
  act(() => { vi.advanceTimersByTime(1); });
  pointer('pointerup');
  fireEvent.click(row(), { detail: 1 });
  expect(openSession).not.toHaveBeenCalled();
  for (const [name, callback] of [['复制会话', copySession], ['共享设置', shareSession], ['删除', deleteSession]] as const) {
    fireEvent.click(screen.getByRole('button', { name }));
    expect(callback).toHaveBeenCalledWith('one');
  }
  // The next deliberate tap works normally.
  pointer('pointerdown'); pointer('pointerup'); fireEvent.click(row(), { detail: 1 });
  expect(openSession).toHaveBeenCalledWith('one');
});

it.each(['pointerup', 'pointercancel', 'pointerleave', 'move', 'scroll'])('cancels a pending hold on %s', (cancel) => {
  render(React.createElement(Harness));
  pointer('pointerdown');
  if (cancel === 'move') pointer('pointermove', { clientY: 55 });
  else if (cancel === 'scroll') fireEvent.scroll(document.getElementById('session-history-list')!);
  // React derives onPointerLeave from the browser's pointerout event.
  else pointer(cancel === 'pointerleave' ? 'pointerout' : cancel);
  hold();
  expect(toggleMenu).not.toHaveBeenCalled();
});

it('opens the conversation on a short tap', () => {
  render(React.createElement(Harness));
  pointer('pointerdown'); pointer('pointerup'); fireEvent.click(row(), { detail: 1 });
  hold();
  expect(openSession).toHaveBeenCalledWith('one');
  expect(toggleMenu).not.toHaveBeenCalled();
});

it('preserves permission checks for shared conversations', () => {
  render(React.createElement(Harness, { owner: 'someone-else' }));
  pointer('pointerdown'); hold();
  expect(screen.getByRole('button', { name: '复制会话' })).toBeTruthy();
  expect(screen.queryByRole('button', { name: '共享设置' })).toBeNull();
  expect(screen.queryByRole('button', { name: '删除' })).toBeNull();
});

it('keeps the desktop more button and ignores desktop holds and mobile mouse holds', () => {
  mobile = false;
  const view = render(React.createElement(Harness));
  pointer('pointerdown'); hold();
  expect(toggleMenu).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '更多操作' }));
  expect(screen.getByRole('button', { name: '删除' })).toBeTruthy();
  view.unmount(); mobile = true; toggleMenu.mockClear();
  render(React.createElement(Harness));
  pointer('pointerdown', { pointerType: 'mouse' }); hold();
  expect(toggleMenu).not.toHaveBeenCalled();
});

it('clears pending timers when closing or unmounting the drawer', () => {
  const view = render(React.createElement(Harness));
  pointer('pointerdown');
  view.rerender(React.createElement(Harness, { open: false })); hold();
  expect(toggleMenu).not.toHaveBeenCalled();
  view.rerender(React.createElement(Harness)); pointer('pointerdown');
  view.unmount(); hold();
  expect(toggleMenu).not.toHaveBeenCalled();
});
