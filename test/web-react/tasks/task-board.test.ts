import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { fireEvent, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { TaskBoard } from '../../../web-react/src/features/tasks/TaskBoard';
import { tasksApi, type TaskList } from '../../../web-react/src/api/tasks';
import { useAppStore } from '../../../web-react/src/stores/appStore';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const cleanup: (() => void)[] = [];
afterEach(() => { cleanup.forEach(f => f()); cleanup.length = 0; vi.restoreAllMocks(); useAppStore.setState({ currentUser: null }); });

async function board() {
  useAppStore.setState({ currentUser: { id: 'ua', username: 'alice', display_name: 'A', role: 'user', status: 'active' } });
  vi.spyOn(tasksApi, 'members').mockResolvedValue({ current_member_id: 'A', members: [
    { member_id: 'A', user_id: 'ua', display_name: '爸爸', aliases: [], status: 'active' },
  ] });
  vi.spyOn(tasksApi, 'summary').mockResolvedValue({ counts: { today: 0, undated: 1, overdue: 0, unclaimed: 0 }, as_of: '2026-10-23T12:00:00+08:00', timezone: 'Asia/Shanghai', revision: 1, history_complete: true });
  const row = { task: { id: 't', title: '牛奶', description: '', category: null, created_by: 'A', space_type: 'personal',
    space_owner_id: 'A', temporal_type: 'undated', actionable: true, assignee_ids: ['A'], related_member_ids: [],
    completion_mode: 'all', lifecycle: 'active', version: 1, starts_on: null, due_date: null, due_at: null, recurrence: null },
    occurrence: { id: 't:once', task_id: 't', due_date: null, due_at: null, status: 'open', version: 1, title_snapshot: '牛奶',
      completion_mode: 'all', assignee_ids: ['A'], member_progress: { A: { status: 'open', completed_at: null } } }, overdue: false, assignee_unavailable: [] };
  const listing = { items: [row], today: '2026-10-23', revision: 1, timezone: 'Asia/Shanghai', as_of: '2026-10-23T12:00:00+08:00', history_complete: true, next_cursor: null, total: 1 } as TaskList;
  vi.spyOn(tasksApi, 'list').mockResolvedValue(listing);
  const container = document.createElement('div'); document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => root.render(React.createElement(TaskBoard)));
  cleanup.push(() => { act(() => root.unmount()); container.remove(); });
  return { listing };
}

it('shows real no-date progress and keeps it unchanged after a failed save', async () => {
  await board();
  vi.spyOn(tasksApi, 'change').mockRejectedValue(new Error('版本冲突，请刷新'));
  expect(screen.getByText('无日期 1', { exact: false })).toBeTruthy();
  await act(async () => fireEvent.click(screen.getByRole('button', { name: '完成', exact: true })));
  expect(screen.getByRole('alert').textContent).toContain('版本冲突');
  expect(screen.getByRole('button', { name: '完成', exact: true })).toBeTruthy();
  expect(screen.queryByRole('button', { name: '撤销完成' })).toBeNull();
});

it('refreshes on task_changed and focus, and does not show a complete historical count during catch-up', async () => {
  const { listing } = await board();
  vi.mocked(tasksApi.list).mockResolvedValue({ ...listing, history_complete: false, total: null });
  await act(async () => window.dispatchEvent(new CustomEvent('task_changed')));
  expect(screen.getByText('历史整理中，历史总数暂不完整。')).toBeTruthy();
  const count = vi.mocked(tasksApi.list).mock.calls.length;
  await act(async () => window.dispatchEvent(new Event('focus')));
  expect(vi.mocked(tasksApi.list).mock.calls.length).toBeGreaterThan(count);
});
