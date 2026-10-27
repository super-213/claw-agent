import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { BoardChatCard } from '../../../web-react/src/features/board/BoardChatCard';
import { BoardMentionInput } from '../../../web-react/src/features/board/BoardMentionInput';
import { WorkbenchPanels } from '../../../web-react/src/features/board/WorkbenchPanels';
import { boardApi, emptyBoardData, type BoardView } from '../../../web-react/src/api/board';
import { clearCardEdits } from '../../../web-react/src/features/interactive-cards/state';
import { useAppStore } from '../../../web-react/src/stores/appStore';

let client: QueryClient;
let current: BoardView;
let submit: ReturnType<typeof vi.fn>;
beforeEach(() => {
  clearCardEdits(); localStorage.clear();
  useAppStore.setState({ currentUser: { id: 'alice', username: 'alice', role: 'user' } });
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  current = { resource: { type: 'board_post_draft', id: 'draft' }, mode: 'draft', post: {
    ...emptyBoardData(), title: '饭在冰箱里', content_blocks: [{ type: 'text', text: '热一下即可。' }],
    id: 'draft', created_by: 'A', version: 1, state: 'draft', created_at: '2026-10-27T04:00:00Z',
  }, server_now: '2026-10-27T04:00:00Z', timezone: 'Asia/Shanghai', valid_until: null, next_transition_at: null,
    current_member_id: 'A', members: [{ member_id: 'A', display_name: '小林', status: 'active' }, { member_id: 'B', display_name: '小陈', status: 'active' }],
    read_only: false, read_only_reason: null, capabilities: { editable_fields: ['title'], actions: ['publish', 'save_draft'] } };
  submit = vi.fn(async () => current);
});
afterEach(() => { cleanup(); client.clear(); clearCardEdits(); vi.restoreAllMocks(); });
function mountCard() {
  return render(React.createElement(MemoryRouter, null, React.createElement(BoardChatCard, {
    view: current, context: { surface: 'chat', sessionId: 'session' }, editKey: 'alice:board-card',
    reference: { type: 'interactive_card', schema_version: 1, kind: 'board_post', card_id: 'card', mode: 'draft', resource: current.resource },
    busy: false, verifying: false, uncertain: false, error: '', retry: vi.fn(), refresh: vi.fn(), submit, savedSequence: 0,
  })));
}
it('submits chosen recipients and relative retention to the original draft without asking a model', async () => {
  mountCard();
  fireEvent.click(screen.getByLabelText('小陈', { exact: true }));
  fireEvent.change(screen.getByLabelText('便笺保留方式'), { target: { value: 'until' } });
  fireEvent.click(screen.getByRole('button', { name: '1 天', exact: true }));
  fireEvent.click(screen.getByRole('button', { name: '发布便笺', exact: true }));
  await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
  expect(submit.mock.calls[0][0]).toMatchObject({ action: 'publish', target: { id: 'draft', type: 'board_post_draft' }, expected_version: 1,
    data: { recipient_ids: ['B'], retention_mode: 'until', duration_hours: 24, expires_at: null } });
});
it('preserves local edits when a draft editor is closed and opened', () => {
  const mounted = mountCard();
  fireEvent.change(screen.getByLabelText('便笺标题'), { target: { value: '还未保存的文字' } });
  mounted.unmount();
  mountCard();
  expect(screen.getByLabelText('便笺标题')).toHaveValue('还未保存的文字');
});
it('blocks publication after failed image upload until the image is explicitly removed', async () => {
  vi.spyOn(boardApi, 'upload').mockRejectedValue(new Error('上传中断'));
  const mounted = mountCard();
  const file = new File(['png'], 'photo.png', { type: 'image/png' });
  fireEvent.change(mounted.container.querySelector('input[type=file]')!, { target: { files: [file] } });
  await screen.findByText('photo.png：上传中断');
  expect(screen.getByRole('button', { name: '发布便笺', exact: true })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: '移除失败图片' }));
  await waitFor(() => expect(screen.getByRole('button', { name: '发布便笺', exact: true })).toBeEnabled());
});
it('hides expired note contents even for the original author', () => {
  current.mode = 'saved'; current.post.state = 'expired'; current.read_only = true;
  current.capabilities = { editable_fields: [], actions: [] };
  mountCard();
  expect(screen.getByText('便笺已到期，无法查看。')).toBeTruthy();
  expect(screen.queryByText('热一下即可。')).toBeNull();
  expect(screen.queryByRole('button', { name: '编辑便笺' })).toBeNull();
  expect(screen.queryByRole('button', { name: '发布便笺' })).toBeNull();
});
it('offers all household members for bare @ without converting the input to a task command', () => {
  const change = vi.fn();
  render(React.createElement(BoardMentionInput, { text: '@ ', onChange: change,
    members: [{ member_id: 'B', user_id: 'bob', display_name: '小陈', aliases: [], status: 'active' }], disabled: false,
    children: () => React.createElement('textarea') }));
  fireEvent.click(screen.getByRole('option', { name: '小陈', exact: true }));
  expect(change).toHaveBeenCalledWith('@ 小陈 ');
});
it('switches workbench panels without discarding widget layout or leaking data across accounts', async () => {
  vi.spyOn(boardApi, 'list').mockResolvedValue({ items: [], next_cursor: null, server_now: '2026-10-27T04:00:00Z' });
  const FixtureWidgets = ({ panelSwitch }: { panelSwitch?: React.ReactNode }) => React.createElement('div', null, panelSwitch, '原来的小组件');
  const child = React.createElement(FixtureWidgets);
  render(React.createElement(MemoryRouter, null, React.createElement(QueryClientProvider, { client }, React.createElement(WorkbenchPanels, { userId: 'alice', children: child }))));
  expect(screen.getByText('原来的小组件')).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: '留言板', exact: true }));
  await screen.findByRole('button', { name: '写便笺', exact: true });
  expect(screen.queryByRole('combobox', { name: '便笺来源' })).toBeNull();
  expect(screen.queryByRole('combobox', { name: '便笺状态' })).toBeNull();
  expect(boardApi.list).toHaveBeenCalledWith(null);
  expect(localStorage.getItem('claw.home.panel.v1.alice')).toBe('board');
  expect(localStorage.getItem('claw.home.panel.v1.bob')).toBeNull();
});
