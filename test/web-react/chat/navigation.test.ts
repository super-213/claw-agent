import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ChatWorkspace } from '../../../web-react/src/features/chat/ChatWorkspace';
import { useAppStore } from '../../../web-react/src/stores/appStore';

let mobile = false;
beforeEach(() => {
  mobile = false;
  localStorage.clear();
  window.matchMedia = vi.fn().mockImplementation(() => ({
    matches: mobile, addEventListener: vi.fn(), removeEventListener: vi.fn(),
  }));
  useAppStore.setState({ currentUser: null, sessions: [], messages: [], streams: {}, currentSessionId: null });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); localStorage.clear(); });
const mount = () => render(React.createElement(MemoryRouter, {}, React.createElement(ChatWorkspace, { active: false })));

it('collapses history, retains global navigation, and remembers the choice after remounting', () => {
  const view = mount();
  fireEvent.click(screen.getByRole('button', { name: '收起历史对话' }));
  expect(document.getElementById('chat-session-sidebar')).toHaveAttribute('hidden');
  expect(screen.getByRole('navigation', { name: '主导航' })).toBeTruthy();
  expect(screen.getByRole('button', { name: '展开历史对话' })).toHaveAttribute('aria-expanded', 'false');
  view.unmount();
  mount();
  expect(document.getElementById('chat-session-sidebar')).toHaveAttribute('hidden');
  fireEvent.click(screen.getByRole('button', { name: '展开历史对话' }));
  expect(document.getElementById('chat-session-sidebar')).not.toHaveAttribute('hidden');
  expect(localStorage.getItem('claw-chat-sidebar-collapsed')).toBe('false');
});

it('can open the mobile history drawer even when desktop history was collapsed', () => {
  mobile = true;
  localStorage.setItem('claw-chat-sidebar-collapsed', 'true');
  mount();
  fireEvent.click(screen.getByRole('button', { name: '打开历史对话' }));
  expect(screen.getByRole('dialog', { name: '历史对话' })).not.toHaveAttribute('hidden');
  expect(screen.getByRole('button', { name: '打开历史对话' })).toHaveAttribute('aria-expanded', 'true');
});

it('keeps account and admin shortcuts in the single global Agent menu', () => {
  mount();
  expect(screen.queryByRole('button', { name: '打开账号与管理菜单' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '家庭 Agent 快捷导航' }));
  expect(screen.getByRole('link', { name: '账号与设置' })).toHaveAttribute('href', '/home/more?section=account');
});

it('shows connection loss in the header and restores the current task status only after a fresh response', () => {
  useAppStore.setState({ statusText: '就绪' });
  mount();
  const badge = screen.getByRole('status');
  expect(badge).toHaveTextContent('就绪');
  fireEvent(window, new Event('claw-cache-fallback'));
  expect(badge).toHaveTextContent('连接中断');
  expect(badge).toHaveAttribute('title', expect.stringContaining('已缓存的数据'));
  // Browser connectivity alone does not confirm that the server has recovered.
  fireEvent(window, new Event('online'));
  expect(badge).toHaveTextContent('连接中断');
  Object.defineProperty(window.navigator, 'onLine', { configurable: true, value: false });
  fireEvent(window, new Event('offline'));
  expect(badge).toHaveTextContent('离线');
  Object.defineProperty(window.navigator, 'onLine', { configurable: true, value: true });
  fireEvent(window, new Event('online'));
  fireEvent(window, new Event('claw-cache-fresh'));
  expect(badge).toHaveTextContent('就绪');
});
