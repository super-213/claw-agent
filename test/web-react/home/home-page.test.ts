import React from 'react';
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { HomePage } from '../../../web-react/src/features/home/HomePage';
import { homeApi } from '../../../web-react/src/api/home';
import { tasksApi, type TaskList } from '../../../web-react/src/api/tasks';
import { useAppStore } from '../../../web-react/src/stores/appStore';

vi.mock('../../../web-react/src/features/chat/ChatWorkspace', () => ({
  ChatWorkspace: () => null,
}));
const list: TaskList = {
  items: [],
  today: '2026-10-23',
  revision: 1,
  timezone: 'Asia/Shanghai',
  as_of: '2026-10-23T12:00:00+08:00',
  history_complete: true,
  next_cursor: null,
  total: 0,
};
let client: QueryClient;
beforeEach(() => {
  window.history.replaceState(null, '', '/home');
  window.matchMedia = vi.fn().mockImplementation((query) => ({
    matches: query.includes('767'),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
  useAppStore.setState({
    currentUser: {
      id: 'home-tester',
      username: 'tester',
      display_name: '示例',
      role: 'user',
      status: 'active',
    },
  });
  client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  vi.spyOn(tasksApi, 'members').mockResolvedValue({
    current_member_id: 'A',
    members: [],
  });
  localStorage.clear();
  vi.spyOn(tasksApi, 'summary').mockResolvedValue({
    counts: { undated: 0 },
    revision: 1,
    timezone: 'Asia/Shanghai',
    as_of: list.as_of,
    history_complete: true,
  });
  vi.spyOn(tasksApi, 'list').mockResolvedValue(list);
  vi.spyOn(homeApi, 'inventory').mockImplementation(async (location) => ({
    today: '2026-10-23',
    timezone: 'Asia/Shanghai',
    items:
      location === 'fridge'
        ? [
            {
              id: 'milk',
              name: '示例牛奶',
              location: 'fridge',
              expires_at: '2026-10-24',
              quantity: 1,
              unit: '盒',
              status: 'available',
            },
          ]
        : [],
  }));
});
afterEach(() => {
  cleanup();
  client.clear();
  vi.restoreAllMocks();
  useAppStore.setState({ currentUser: null });
});
const mount = () =>
  render(
    React.createElement(
      BrowserRouter,
      {},
      React.createElement(
        QueryClientProvider,
        { client },
        React.createElement(HomePage),
      ),
    ),
  );

it('keeps successful inventory usable when tasks fail, without presenting a false zero count', async () => {
  vi.mocked(tasksApi.list).mockRejectedValue(new Error('查询失败'));
  mount();
  await screen.findByRole('heading', { name: '先看看已读取的事项' });
  expect(screen.getAllByRole('button', { name: /示例牛奶/ })[0]).toBeTruthy();
  expect(screen.getByText(/部分数据暂时无法读取/)).toBeTruthy();
  expect(screen.queryByText('今天暂无待处理事项')).toBeNull();
  vi.mocked(tasksApi.list).mockResolvedValue(list);
  fireEvent.click(
    screen.getByText(/部分数据暂时无法读取/).querySelector('button')!,
  );
  await screen.findByRole('heading', { name: '有 1 件事需要关注' });
});
it('follows pagination and retains last successful content after refresh failure', async () => {
  vi.mocked(tasksApi.list)
    .mockResolvedValueOnce({ ...list, next_cursor: '200' })
    .mockResolvedValue(list);
  mount();
  await screen.findByRole('heading', { name: '有 1 件事需要关注' });
  expect(
    vi
      .mocked(tasksApi.list)
      .mock.calls.some(([filters]) => filters?.cursor === '200'),
  ).toBe(true);
  vi.mocked(homeApi.inventory).mockRejectedValue(new Error('离线'));
  await act(async () => {
    window.dispatchEvent(new CustomEvent('inventory_changed'));
  });
  await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy());
  expect(screen.getAllByRole('button', { name: /示例牛奶/ })[0]).toBeTruthy();
});
it('reports failed writes without removing the item or claiming completion', async () => {
  vi.spyOn(homeApi, 'consumeInventoryItem').mockRejectedValue(
    new Error('保存失败，请重试'),
  );
  mount();
  await screen.findByRole('heading', { name: '有 1 件事需要关注' });
  fireEvent.click(screen.getByRole('button', { name: '用完', exact: true }));
  await screen.findByText('保存失败，请重试');
  expect(screen.getAllByRole('button', { name: /示例牛奶/ })[0]).toBeTruthy();
  expect(screen.queryByText('示例牛奶 已标记用完')).toBeNull();
});
