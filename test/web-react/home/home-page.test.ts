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
import { authApi } from '../../../web-react/src/api/auth';
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

it('completes an overdue attention item using its original occurrence and refreshes the list', async () => {
  vi.mocked(homeApi.inventory).mockResolvedValue({ today: list.today, timezone: list.timezone, items: [] });
  const row: TaskList['items'][number] = {
    task: { id: 'late', title: '已做完忘勾选', description: '', category: null, created_by: 'A',
      space_type: 'personal', space_owner_id: 'A', temporal_type: 'timed', actionable: true,
      assignee_ids: ['A'], related_member_ids: [], completion_mode: 'all', lifecycle: 'active',
      version: 1, starts_on: null, due_date: '2026-10-21', due_at: null, recurrence: null },
    occurrence: { id: 'late:once', task_id: 'late', title_snapshot: '已做完忘勾选', due_date: '2026-10-21',
      due_at: null, status: 'open', version: 3, completion_mode: 'all', assignee_ids: ['A'],
      member_progress: { A: { status: 'open', completed_at: null } } },
    overdue: true, assignee_unavailable: [],
  };
  vi.mocked(tasksApi.list).mockResolvedValue({ ...list, items: [row], total: 1 });
  const change = vi.spyOn(tasksApi, 'change').mockImplementation(async () => {
    vi.mocked(tasksApi.list).mockResolvedValue(list);
    return {};
  });
  mount();
  await screen.findByRole('heading', { name: '有 1 件事需要关注' });
  expect(screen.getByText(/已逾期/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: '完成', exact: true }));
  await waitFor(() => expect(change).toHaveBeenCalledWith('late', 'complete', { expected_version: 3 }, 'late:once'));
  await waitFor(() => expect(screen.queryByText('已做完忘勾选')).toBeNull());
});

it('keeps four primary destinations and groups miscellaneous tools without duplicate chat history', async () => {
  window.history.replaceState(null, '', '/home/more');
  mount();
  expect(screen.getAllByRole('heading', { name: '更多', exact: true })).toHaveLength(1);
  const nav = screen.getByRole('navigation', { name: '手机主导航' });
  expect(nav.querySelectorAll('a')).toHaveLength(4);
  expect(screen.getByRole('heading', { name: '个人设置' })).toBeTruthy();
  expect(screen.getByRole('heading', { name: '便捷使用' })).toBeTruthy();
  expect(screen.getByRole('link', { name: /查看、添加和重载对话技能/ })).toHaveAttribute('href', '/home/more?section=skills');
  expect(screen.queryByRole('link', { name: /最近对话/ })).toBeNull();
  expect(screen.queryByRole('link', { name: /离线随身页/ })).toBeNull();
  expect(screen.queryByRole('heading', { name: '管理员工具' })).toBeNull();
  expect(screen.queryByRole('group', { name: '外观' })).toBeNull();
  fireEvent.click(screen.getByRole('link', { name: /物品操作记录/ }));
  expect(window.location.search).toBe('?section=activity');
  expect(screen.getByRole('heading', { name: '物品操作记录' })).toBeTruthy();
  fireEvent.click(screen.getByRole('link', { name: '返回更多' }));
  expect(window.location.pathname + window.location.search).toBe('/home/more');
  expect(screen.getByRole('heading', { name: '便捷使用' })).toBeTruthy();
});

it('opens account without application preferences and returns from a direct link', async () => {
  window.history.replaceState(null, '', '/home/more?section=account');
  mount();
  expect(screen.getByRole('heading', { name: '账号' })).toHaveFocus();
  expect(screen.queryByRole('group', { name: '外观' })).toBeNull();
  expect(screen.getByRole('heading', { name: '个人资料' })).toBeTruthy();
  fireEvent.click(screen.getByRole('link', { name: '返回更多' }));
  expect(window.location.search).toBe('');
  expect(screen.getByRole('heading', { name: '更多' })).toHaveFocus();
});

it('keeps the member admin inside the shared navigation and returns to the menu', async () => {
  useAppStore.setState({ currentUser: { ...useAppStore.getState().currentUser!, role: 'admin' } });
  window.history.replaceState(null, '', '/home/more');
  mount();
  fireEvent.click(screen.getByRole('link', { name: /家庭成员管理/ }));
  expect(screen.getByRole('heading', { name: '家庭成员管理' })).toBeTruthy();
  expect(screen.getByText('家庭成员绑定与迁移核对（管理员）')).toBeTruthy();
  fireEvent.click(screen.getByRole('link', { name: '返回更多' }));
  expect(screen.getByRole('heading', { name: '管理员工具' })).toBeTruthy();
});

it.each(['unknown', 'admin', 'toString'])('recovers invalid or unauthorized More section %s', async (section) => {
  window.history.replaceState(null, '', `/home/more?section=${section}`);
  mount();
  await waitFor(() => expect(window.location.search).toBe(''));
  expect(screen.getByRole('heading', { name: '便捷使用' })).toBeTruthy();
  expect(screen.queryByText('家庭成员绑定与迁移核对（管理员）')).toBeNull();
});


it('separates settings from account and hides administrator configuration for regular users', async () => {
  window.history.replaceState(null, '', '/home/more');
  mount();
  expect(screen.getByRole('link', { name: /账号.*个人资料/ })).toHaveAttribute('href', '/home/more?section=account');
  fireEvent.click(screen.getByRole('link', { name: /设置.*外观与回复通知/ }));
  expect(screen.getByRole('heading', { name: '设置' })).toHaveFocus();
  expect(screen.getByRole('group', { name: '外观' })).toBeTruthy();
  expect(screen.queryByRole('button', { name: '退出登录' })).toBeNull();
  expect(screen.queryByText('管理员设置')).toBeNull();
});

it('edits the display name and refreshes the current identity', async () => {
  window.history.replaceState(null, '', '/home/more?section=account');
  const updated = { ...useAppStore.getState().currentUser!, display_name: '新的称呼' };
  const cacheUpdate = vi.spyOn(client, 'setQueryData');
  const save = vi.spyOn(authApi, 'updateProfile').mockResolvedValue({ ok: true, user: updated });
  mount();
  fireEvent.click(screen.getByRole('button', { name: '修改显示名称' }));
  fireEvent.change(screen.getByRole('textbox', { name: '显示名称' }), { target: { value: ' 新的称呼 ' } });
  fireEvent.click(screen.getByRole('button', { name: '保存名称' }));
  await screen.findByText('显示名称已更新。');
  expect(save).toHaveBeenCalledWith('新的称呼');
  expect(useAppStore.getState().currentUser?.display_name).toBe('新的称呼');
  expect(cacheUpdate).toHaveBeenCalledWith(['auth', 'me'], updated);
});

it('validates password confirmation, reports server errors and clears secrets when collapsed', async () => {
  window.history.replaceState(null, '', '/home/more?section=account');
  const save = vi.spyOn(authApi, 'changePassword').mockRejectedValue(new Error('当前密码不正确'));
  mount();
  fireEvent.click(screen.getByRole('button', { name: /修改密码/ }));
  fireEvent.change(screen.getByLabelText('当前密码'), { target: { value: 'wrong-password' } });
  fireEvent.change(screen.getByLabelText('新密码', { exact: true }), { target: { value: 'new-password' } });
  fireEvent.change(screen.getByLabelText('确认新密码'), { target: { value: 'different-password' } });
  fireEvent.click(screen.getByRole('button', { name: '保存并重新登录' }));
  expect(screen.getByRole('alert')).toHaveTextContent('两次输入的新密码不一致');
  expect(save).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText('确认新密码'), { target: { value: 'new-password' } });
  fireEvent.click(screen.getByRole('button', { name: '保存并重新登录' }));
  await screen.findByText('当前密码不正确');
  fireEvent.click(screen.getByRole('button', { name: '取消' }));
  fireEvent.click(screen.getByRole('button', { name: /修改密码/ }));
  expect(screen.getByLabelText('当前密码')).toHaveValue('');
  expect(screen.getByLabelText('新密码', { exact: true })).toHaveValue('');
});

it('explains missing household membership instead of a generic read error', async () => {
  const { ApiError } = await import('../../../web-react/src/api/client');
  vi.mocked(tasksApi.list).mockRejectedValue(new ApiError('请管理员先将当前账号绑定为家庭成员。', new Response(null, { status: 403 }), { error: 'member_not_bound' }));
  mount();
  expect(await screen.findByText(/当前账号尚未绑定家庭成员/)).toBeTruthy();
  expect(screen.queryByText(/部分数据暂时无法读取/)).toBeNull();
});
