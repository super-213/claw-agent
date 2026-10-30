import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { InteractiveCardHost } from '../../../web-react/src/features/interactive-cards/InteractiveCardHost';
import { registerCardAdapter } from '../../../web-react/src/features/interactive-cards/registry';
import { clearCardEdits } from '../../../web-react/src/features/interactive-cards/state';
import type { CardRenderProps, CardView, InteractiveCardRef } from '../../../web-react/src/features/interactive-cards/types';
import { taskCardAdapter, type TaskCardAction, type TaskCardView } from '../../../web-react/src/features/tasks/taskCardAdapter';
import { cardTimestamp } from '../../../web-react/src/features/tasks/taskCardTime';
import { useAppStore } from '../../../web-react/src/stores/appStore';
import { ApiError } from '../../../web-react/src/api/client';
import { MessageRows } from '../../../web-react/src/features/chat/MessageRows';

let counter = 0;
let client: QueryClient;
let current: TaskCardView;
let ref: InteractiveCardRef;
let load: ReturnType<typeof vi.fn>;
let submit: ReturnType<typeof vi.fn>;
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

beforeEach(() => {
  clearCardEdits();
  useAppStore.setState({ currentUser: { id: 'owner', username: 'alice', role: 'admin' } });
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  current = {
    mode: 'saved', resource: { type: 'family_task', id: 'task-1', instance_id: 'task-1:once' },
    server_now: '2026-10-27T12:00:00+08:00', timezone: 'Asia/Shanghai', time_state: 'upcoming',
    valid_until: '2026-10-29T00:00:00+08:00', next_transition_at: '2026-10-28T00:00:00+08:00',
    read_only: false, read_only_reason: null, current_member_id: 'A',
    members: [{ member_id: 'A', display_name: '小林', status: 'active', aliases: [] }, { member_id: 'B', display_name: '小陈', status: 'active', aliases: [] }],
    capabilities: { editable_fields: ['title', 'due_date', 'space_type', 'assignee_ids'], actions: ['save', 'complete', 'archive'] },
    task: { id: 'task-1', title: '去上海', description: '', category: null, created_by: 'A', space_type: 'personal',
      space_owner_id: 'A', temporal_type: 'timed', actionable: true, assignee_ids: ['A'], related_member_ids: [],
      completion_mode: 'all', lifecycle: 'active', version: 1, starts_on: null, due_date: '2026-10-28', due_at: null, recurrence: null },
    occurrence: { id: 'task-1:once', task_id: 'task-1', due_date: '2026-10-28', due_at: null, status: 'open', version: 1,
      title_snapshot: '去上海', assignee_ids: ['A'], completion_mode: 'all', member_progress: { A: { status: 'open', completed_at: null } } },
  };
  const kind = `test-task-${++counter}`;
  ref = { type: 'interactive_card', schema_version: 1, kind, card_id: `card-${counter}`, mode: 'saved', resource: current.resource };
  load = vi.fn(async () => clone(current));
  submit = vi.fn(async (_ref: InteractiveCardRef, action: TaskCardAction) => {
    const patch = action.definition_patch || action.occurrence_patch || {};
    Object.assign(current.task!, patch, { version: current.task!.version + 1 });
    Object.assign(current.occurrence!, {
      title_snapshot: patch.title || current.occurrence!.title_snapshot,
      due_date: patch.due_date || current.occurrence!.due_date,
      version: current.occurrence!.version + 1,
    });
    return clone(current);
  });
  registerCardAdapter({ ...taskCardAdapter, kind, load, submit });
});
afterEach(() => { cleanup(); client.clear(); vi.restoreAllMocks(); clearCardEdits(); });
function mount(children = React.createElement(InteractiveCardHost, { reference: ref, context: { surface: 'chat', sessionId: 'session' } })) {
  return render(React.createElement(QueryClientProvider, { client }, children));
}
async function editTitle(value: string) {
  fireEvent.click(await screen.findByRole('button', { name: '调整事项' }));
  fireEvent.change(screen.getByLabelText('标题'), { target: { value } });
}

it('keeps edits local, saves the same resource, and submits title date space and stable members together', async () => {
  mount();
  await editTitle('出发去上海');
  fireEvent.change(screen.getByLabelText('日期'), { target: { value: '2026-10-29' } });
  fireEvent.change(screen.getByLabelText('空间'), { target: { value: 'household' } });
  fireEvent.click(screen.getByLabelText('小陈'));
  expect(submit).not.toHaveBeenCalled();
  expect(current.task!.title).toBe('去上海');
  expect(screen.getByText('有未保存的修改')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: '保存修改' }));
  await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
  const [submittedRef, action, context, requestId] = submit.mock.calls[0];
  expect(submittedRef.resource.id).toBe('task-1');
  expect(action.definition_patch).toMatchObject({ title: '出发去上海', due_date: '2026-10-29', space_type: 'household', assignee_ids: ['A', 'B'] });
  expect(action.audience_confirmed).toBe(true);
  expect(context.sessionId).toBe('session');
  expect(typeof requestId).toBe('string');
  await waitFor(() => expect(screen.queryByText('有未保存的修改')).toBeNull());
  expect(await screen.findByRole('heading', { name: '出发去上海' })).toBeTruthy();
});

it('discards only the pending edit without archiving or recreating the saved record', async () => {
  mount();
  await editTitle('不保存');
  fireEvent.click(screen.getByRole('button', { name: '放弃修改' }));
  expect(submit).not.toHaveBeenCalled();
  expect(screen.getByRole('heading', { name: '去上海' })).toBeTruthy();
  expect(screen.queryByLabelText('标题')).toBeNull();
});

it('searches member aliases and distinguishes identical names while submitting stable identities', async () => {
  current.members = [
    { member_id: 'A', display_name: '小林', status: 'inactive', aliases: [] },
    { member_id: 'B', display_name: '小陈', status: 'active', aliases: ['爸爸'] },
    { member_id: 'C', display_name: '小陈', status: 'active', aliases: ['叔叔'] },
    ...['D', 'E', 'F', 'G'].map(member_id => ({ member_id, display_name: `家人${member_id}`, status: 'active', aliases: [] })),
  ];
  mount();
  await editTitle('同名家人的事项');
  expect(screen.getByLabelText('小陈（爸爸）')).toBeTruthy();
  expect(screen.getByLabelText('小陈（叔叔）')).toBeTruthy();
  fireEvent.change(screen.getByRole('searchbox', { name: '搜索负责人' }), { target: { value: '叔叔' } });
  expect(screen.queryByLabelText('小陈（爸爸）')).toBeNull();
  expect(screen.getByLabelText('小林（已停用）')).toBeChecked();
  fireEvent.click(screen.getByLabelText('小林（已停用）'));
  fireEvent.click(screen.getByLabelText('小陈（叔叔）'));
  fireEvent.click(screen.getByRole('button', { name: '保存修改' }));
  await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
  expect(submit.mock.calls[0][1].definition_patch.assignee_ids).toEqual(['C']);
});

it('retains pending field edits while the card is unmounted and remounted', async () => {
  const first = mount();
  await editTitle('暂存的修改');
  first.unmount();
  mount();
  expect(await screen.findByLabelText('标题')).toHaveValue('暂存的修改');
  expect(submit).not.toHaveBeenCalled();
});

it('deduplicates streamed tool references and places the interactive result after the final assistant reply', async () => {
  const view = mount(React.createElement(MessageRows, {
    onCreateBranch: () => undefined,
    messages: [
      { role: 'assistant', content: '', tool_calls: [{ id: 'call', type: 'function', function: { name: 'family_timed_memo_create', arguments: '{}' } }] },
      { role: 'tool', content: '{}', tool_call_id: 'call', name: 'family_timed_memo_create', ui_blocks: [ref] },
      { role: 'assistant', content: '', ui_blocks: [ref] },
      { role: 'assistant', content: 'fallback text', ui_summary: '已保存，可在卡片中调整。', ui_blocks: [ref] },
    ],
  }));
  const card = await screen.findByRole('article', { name: '日程卡片：去上海' });
  expect(view.container.querySelectorAll('.interactive-card')).toHaveLength(1);
  const summary = screen.getByText('已保存，可在卡片中调整。');
  expect(summary.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.queryByText('fallback text')).toBeNull();
});

it('freezes content after midnight while still allowing late completion', async () => {
  current.server_now = '2026-10-28T23:59:59.900+08:00';
  current.next_transition_at = '2026-10-29T00:00:00+08:00';
  current.time_state = 'in_progress';
  load.mockImplementationOnce(async () => clone(current)).mockImplementation(async () => ({ ...clone(current),
    server_now: '2026-10-29T00:00:00+08:00', time_state: 'expired', read_only: false, read_only_reason: 'expired',
    next_transition_at: null, capabilities: { editable_fields: [], actions: ['complete'] } }));
  mount();
  expect(await screen.findByText('当天 · 正在进行')).toBeTruthy();
  await waitFor(() => expect(screen.getByText('已过期')).toBeTruthy(), { timeout: 2000 });
  expect(screen.queryByRole('button', { name: '调整事项' })).toBeNull();
  expect(screen.getByText('该事项已过期，仍可补标本人完成；其他内容仅供查看。')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: '标记本人完成' }));
  await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
  expect(submit.mock.calls[0][1]).toMatchObject({
    target: { resource: current.resource }, occurrence_action: { action: 'complete', expected_version: 1 },
  });
});

it('retries an uncertain save using the same request identity and payload', async () => {
  let written = false;
  submit.mockImplementation(async (_ref, action) => {
    current.task!.title = String(action.definition_patch.title);
    current.occurrence!.title_snapshot = current.task!.title;
    current.task!.version = 2;
    if (!written) { written = true; throw new Error('response lost'); }
    return clone(current);
  });
  mount();
  await editTitle('断线也不重复');
  fireEvent.click(screen.getByRole('button', { name: '保存修改' }));
  fireEvent.click(await screen.findByRole('button', { name: '核实并重试' }));
  await waitFor(() => expect(submit).toHaveBeenCalledTimes(2));
  expect(submit.mock.calls[0][3]).toBe(submit.mock.calls[1][3]);
  expect(submit.mock.calls[0][1]).toEqual(submit.mock.calls[1][1]);
  await waitFor(() => expect(screen.queryByText('有未保存的修改')).toBeNull());
});

it('retains the uncertain request identity across navigation and reconciles the saved response', async () => {
  submit.mockRejectedValueOnce(new Error('response lost'));
  const first = mount();
  await editTitle('切回后核实');
  fireEvent.click(screen.getByRole('button', { name: '保存修改' }));
  await screen.findByRole('button', { name: '核实并重试' });
  const original = submit.mock.calls[0];
  first.unmount();
  mount();
  fireEvent.click(await screen.findByRole('button', { name: '核实并重试' }));
  await waitFor(() => expect(submit).toHaveBeenCalledTimes(2));
  expect(submit.mock.calls[1][3]).toBe(original[3]);
  expect(submit.mock.calls[1][1]).toEqual(original[1]);
  expect(await screen.findByRole('heading', { name: '切回后核实' })).toBeTruthy();
  await waitFor(() => expect(screen.queryByText('有未保存的修改')).toBeNull());
});

it('preserves local input on conflict and rebases only fields the user actually changed', async () => {
  submit.mockImplementationOnce(async () => {
    current.task!.title = '另一端的标题'; current.task!.description = '另一端的新备注'; current.task!.version = 2;
    current.occurrence!.version = 2; current.occurrence!.title_snapshot = '另一端的标题';
    throw new ApiError('事项已被更新', new Response('{}', { status: 409 }), { error: 'version_conflict' });
  });
  mount();
  await editTitle('我的标题');
  fireEvent.click(screen.getByRole('button', { name: '保存修改' }));
  const rebase = await screen.findByRole('button', { name: '保留我的修改，按最新版本重新核对' });
  expect(screen.getByLabelText('标题')).toHaveValue('我的标题');
  fireEvent.click(rebase);
  expect(screen.getByLabelText('备注')).toHaveValue('另一端的新备注');
  fireEvent.click(screen.getByRole('button', { name: '保存修改' }));
  await waitFor(() => expect(submit).toHaveBeenCalledTimes(2));
  expect(submit.mock.calls[1][1].expected_task_version).toBe(2);
  expect(submit.mock.calls[1][1].definition_patch).toEqual({ title: '我的标题' });
  expect(submit.mock.calls[0][3]).not.toBe(submit.mock.calls[1][3]);
});

it('shows the same resource in chat and a workbench container and synchronizes an edit', async () => {
  mount(React.createElement(React.Fragment, {},
    React.createElement(InteractiveCardHost, { reference: ref, context: { surface: 'chat' } }),
    React.createElement(InteractiveCardHost, { reference: { ...ref, card_id: 'board-placement' }, context: { surface: 'workbench_board' } })));
  await waitFor(() => expect(screen.getAllByRole('heading', { name: '去上海' })).toHaveLength(2));
  const first = within(screen.getAllByRole('article')[0]);
  fireEvent.click(first.getByRole('button', { name: '调整事项' }));
  fireEvent.change(first.getByLabelText('标题'), { target: { value: '两处同步' } });
  fireEvent.click(first.getByRole('button', { name: '保存修改' }));
  await waitFor(() => expect(screen.getAllByRole('heading', { name: '两处同步' })).toHaveLength(2));
});

it('hides previously loaded private fields when a refreshed authorization check fails', async () => {
  mount();
  await screen.findByRole('heading', { name: '去上海' });
  load.mockRejectedValue(new ApiError('forbidden', new Response('{}', { status: 403 }), {}));
  act(() => { window.dispatchEvent(new CustomEvent('resource_changed')); });
  expect(await screen.findByText('该记录已不可访问。')).toBeTruthy();
  expect(screen.queryByText('去上海')).toBeNull();
});

it('renders an incomplete draft, submits its date directly, and turns the same placement into a saved card', async () => {
  const saved = clone(current);
  current = { ...current, mode: 'draft', resource: { type: 'task_draft', id: 'draft-1' }, task: undefined, occurrence: null,
    draft: { id: 'draft-1', version: 1, items: [{ title: '去上海' }], invocation: { temporal_type: 'timed', space_type: 'personal' } },
    capabilities: { editable_fields: ['items'], actions: ['create'] } };
  ref = { ...ref, resource: current.resource, mode: 'draft' };
  submit.mockImplementation(async () => { current = saved; return clone(saved); });
  mount();
  const date = await screen.findByLabelText('日期');
  fireEvent.change(date, { target: { value: '2026-10-28' } });
  fireEvent.click(screen.getByRole('button', { name: '创建事项' }));
  await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
  expect(submit.mock.calls[0][1].items[0].due_date).toBe('2026-10-28');
  expect(await screen.findByRole('heading', { name: '去上海' })).toBeTruthy();
  expect(screen.queryByText('尚未创建')).toBeNull();
});

it('registers a poll-like test adapter without modifying chat or applying task-day expiry rules', async () => {
  const kind = `poll-fixture-${counter}`;
  const open: CardView = { mode: 'saved', resource: { type: 'family_poll', id: 'poll' },
    server_now: '2026-10-28T10:04:59.900+08:00', valid_until: '2026-10-28T10:05:00+08:00', next_transition_at: '2026-10-28T10:05:00+08:00',
    read_only: false, read_only_reason: null, capabilities: { editable_fields: [], actions: ['vote'] } };
  const closed = { ...open, server_now: '2026-10-28T10:05:00+08:00', next_transition_at: null,
    read_only: true, read_only_reason: 'voting_closed', capabilities: { editable_fields: [], actions: [] } };
  const pollLoad = vi.fn(async () => clone(closed)).mockImplementationOnce(async () => clone(open));
  const vote = vi.fn(async () => clone(open));
  const Poll = (props: CardRenderProps<CardView, { action: 'vote' }>) => props.view.read_only
    ? React.createElement('p', null, '投票已截止，仍可查看结果')
    : React.createElement('button', { disabled: props.verifying, onClick: () => void props.submit({ action: 'vote' }) }, '投票测试');
  registerCardAdapter({ kind, resourceTypes: ['family_poll'], supportedSchemaVersions: [1], load: pollLoad, submit: vote, Renderer: Poll });
  mount(React.createElement(InteractiveCardHost, { reference: { ...ref, kind, resource: { type: 'family_poll', id: 'poll' } }, context: { surface: 'workbench_board' } }));
  fireEvent.click(await screen.findByRole('button', { name: '投票测试' }));
  await waitFor(() => expect(vote).toHaveBeenCalledTimes(1));
  expect(await screen.findByText('投票已截止，仍可查看结果')).toBeTruthy();
  expect(screen.queryByRole('button', { name: '投票测试' })).toBeNull();
});

it('refreshes a relay-like domain when it closes without depending on task status or versions', async () => {
  const kind = `relay-fixture-${counter}`;
  let closed = false;
  const relay: CardView = { mode: 'saved', resource: { type: 'family_relay', id: 'relay' }, server_now: '2026-10-28T10:00:00+08:00',
    valid_until: null, next_transition_at: null, read_only: false, read_only_reason: null,
    capabilities: { editable_fields: ['own_entry'], actions: ['join'] } };
  registerCardAdapter({ kind, resourceTypes: ['family_relay'], supportedSchemaVersions: [1],
    load: async () => ({ ...relay, read_only: closed, capabilities: { editable_fields: [], actions: closed ? [] : ['join'] } }),
    submit: async () => relay,
    Renderer: ({ view }) => React.createElement('p', null, view.capabilities.actions.includes('join') ? '可加入接龙' : '接龙已关闭'),
  });
  mount(React.createElement(InteractiveCardHost, { reference: { ...ref, kind, resource: relay.resource } }));
  expect(await screen.findByText('可加入接龙')).toBeTruthy();
  closed = true;
  act(() => window.dispatchEvent(new CustomEvent('resource_changed', { detail: { resource_type: 'family_relay', resource_id: 'relay' } })));
  expect(await screen.findByText('接龙已关闭')).toBeTruthy();
});

it('falls back for unsupported schema versions without loading or executing a resource', () => {
  mount(React.createElement(InteractiveCardHost, { reference: { ...ref, schema_version: 999 } }));
  expect(screen.getByText('当前版本暂不支持这张卡片，请查看文字结果。')).toBeTruthy();
  expect(load).not.toHaveBeenCalled(); expect(submit).not.toHaveBeenCalled();
});

it('converts dates using the household timezone and rejects nonexistent daylight-saving times', () => {
  expect(cardTimestamp('2026-10-28', '17:34', 'Asia/Shanghai')).toBe('2026-10-28T09:34:00.000Z');
  expect(() => cardTimestamp('2026-03-08', '02:30', 'America/Los_Angeles')).toThrow('当前时区不存在');
});
