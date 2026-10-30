import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ActivityCard } from '../../../web-react/src/features/family-activities/ActivityCard';
import { ActivityToolMenu } from '../../../web-react/src/features/family-activities/ActivityToolMenu';
import { activityTimeISO, localActivityTime } from '../../../web-react/src/features/family-activities/activityTime';
import { activityRef, emptyActivity, type ActivityView } from '../../../web-react/src/api/familyActivities';
import { clearCardEdits } from '../../../web-react/src/features/interactive-cards/state';

let view: ActivityView;
let submit: ReturnType<typeof vi.fn>;
beforeEach(() => {
  clearCardEdits(); submit = vi.fn(async () => view);
  view = { resource: { type: 'family_poll', id: 'poll_1' }, mode: 'saved', activity: { ...emptyActivity(), id: 'poll_1', kind: 'poll', created_by: 'A', version: 1, revision: 1, state: 'open', close_reason: null, completion_member_ids: ['A', 'B'], missing_fields: [], options: [{ id: 'a', text: '火锅' }, { id: 'b', text: '烧烤' }], counts: { a: 0, b: 0 } }, participants: [], own_participation: null, participation_version: 0, current_member_id: 'B', server_now: '2026-10-30T04:00:00Z', valid_until: null, next_transition_at: null, read_only: false, read_only_reason: null, timezone: 'Asia/Shanghai', members: [{ member_id: 'A', display_name: '小林', status: 'active' }, { member_id: 'B', display_name: '小陈', status: 'active' }], capabilities: { actions: ['participate'], editable_fields: [] } };
});
afterEach(() => { cleanup(); clearCardEdits(); vi.restoreAllMocks(); });
function mount() {
  return render(React.createElement(MemoryRouter, {}, React.createElement(ActivityCard, { view, reference: activityRef(view), context: { surface: 'workbench_board' }, editKey: 'test-card', submit, busy: false, verifying: false, uncertain: false, error: '', retry: vi.fn(), refresh: vi.fn(), savedSequence: 0 })));
}
it('submits the authenticated member vote by stable option id without management actions', async () => {
  mount(); fireEvent.click(screen.getByRole('radio', { name: /火锅/ }));
  fireEvent.click(screen.getByRole('button', { name: '提交投票' }));
  await waitFor(() => expect(submit).toHaveBeenCalledOnce());
  expect(submit.mock.calls[0][0]).toMatchObject({ action: 'participate', participation_version: 0, target: view.resource, data: { option_ids: ['a'] } });
  expect(screen.queryByRole('button', { name: '管理活动' })).toBeNull();
});
it('shows frozen results with no participation buttons but still lets creator delete', () => {
  view.activity.state = 'closed'; view.activity.close_reason = 'all_completed'; view.capabilities.actions = ['delete'];
  mount(); expect(screen.getByText('全员已完成，结果只读。')).toBeVisible();
  expect(screen.queryByRole('button', { name: '提交投票' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '删除活动' }));
  expect(submit).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '确认删除' }));
  expect(submit.mock.calls[0][0].action).toBe('delete');
});
it('hides all activity content at the existence boundary even before server cleanup', () => {
  view.valid_until = view.server_now;
  mount(); expect(screen.queryByText('火锅')).toBeNull();
  expect(screen.getByText('该家庭活动已到存在截止时间，无法查看。')).toBeVisible();
});
it('opens a keyboard reachable menu and restores trigger focus on escape', () => {
  const create = vi.fn(); render(React.createElement(ActivityToolMenu, { onCreate: create, disabled: false }));
  const trigger = screen.getByRole('button', { name: '工具' }); fireEvent.click(trigger);
  expect(screen.getByRole('menuitem', { name: '新建家庭接龙' })).toHaveFocus();
  fireEvent.keyDown(screen.getByRole('menu'), { key: 'ArrowDown' });
  expect(screen.getByRole('menuitem', { name: '新建家庭投票' })).toHaveFocus();
  fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' });
  expect(trigger).toHaveFocus(); expect(screen.queryByRole('menu')).toBeNull();
});
it('interprets household time independently of browser timezone and rejects nonexistent DST times', () => {
  expect(activityTimeISO('2026-10-30T20:00', 'Asia/Shanghai')).toBe('2026-10-30T12:00:00.000Z');
  expect(localActivityTime('2026-10-30T12:00:00Z', 'Asia/Shanghai')).toBe('2026-10-30T20:00');
  expect(() => activityTimeISO('2026-03-08T02:30', 'America/Los_Angeles')).toThrow('不存在');
});
