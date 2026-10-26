import { expect, it } from 'vitest';
import {
  addDays,
  buildAttention,
  taskCaption,
} from '../../../web-react/src/features/home/attention';
import type { TaskRow } from '../../../web-react/src/api/tasks';
import type { HomeInventoryItem } from '../../../web-react/src/api/types';

const item = (
  id: string,
  date: string | null,
  status = 'available',
  quantity = 1,
): HomeInventoryItem => ({
  id,
  name: id,
  location: 'fridge',
  expires_at: date,
  status,
  quantity,
  unit: 'kg',
});
const row = (
  id: string,
  date: string | null,
  extra: Partial<TaskRow> = {},
): TaskRow => ({
  task: {
    id,
    title: id,
    description: '',
    category: null,
    created_by: 'A',
    space_type: 'personal',
    space_owner_id: 'A',
    temporal_type: date ? 'timed' : 'undated',
    actionable: true,
    assignee_ids: ['A'],
    related_member_ids: [],
    completion_mode: 'all',
    lifecycle: 'active',
    version: 1,
    starts_on: null,
    due_date: date,
    due_at: null,
    recurrence: null,
  },
  occurrence: {
    id: `${id}:once`,
    task_id: id,
    due_date: date,
    due_at: null,
    status: 'open',
    version: 1,
    title_snapshot: id,
    completion_mode: 'all',
    assignee_ids: ['A'],
    member_progress: { A: { status: 'open', completed_at: null } },
  },
  overdue: Boolean(date && date < '2026-10-23'),
  assignee_unavailable: [],
  ...extra,
});

it('orders overdue and expired first, then today, then the next three days; excludes undated and future tasks', () => {
  const result = buildAttention(
    [
      row('today', '2026-10-23'),
      row('overdue', '2026-10-21'),
      row('memo', null),
      row('future', '2026-10-24'),
    ],
    [
      item('expired', '2026-10-20'),
      item('milk', '2026-10-24'),
      item('cutoff', '2026-10-26'),
      item('later', '2026-10-27'),
    ],
    '2026-10-23',
  );
  expect(result.map((r) => r.title.split(' ')[0])).toEqual([
    'expired',
    'overdue',
    'today',
    'milk',
    'cutoff',
  ]);
});
it('does not resurrect consumed, discarded or completed records, or infer low stock from small quantities', () => {
  const done = row('done', '2026-10-23');
  done.occurrence!.status = 'completed';
  const paused = row('paused', '2026-10-23');
  paused.task.lifecycle = 'paused';
  expect(
    buildAttention(
      [done, paused],
      [
        item('used', '2026-10-20', 'consumed'),
        item('discarded', '2026-10-20', 'discarded'),
        item('one-kilo', null),
        item('low', null, 'low'),
      ],
      '2026-10-23',
    ),
  ).toEqual([]);
});
it('deduplicates shared projections by occurrence, while preserving different weekly instances', () => {
  const current = row('weekly', '2026-10-23');
  const past = row('weekly', '2026-10-16');
  past.occurrence!.id = 'weekly:previous';
  expect(
    buildAttention([current, current, past], [], '2026-10-23'),
  ).toHaveLength(2);
});
it('uses calendar arithmetic independent of browser timezone across year and leap boundaries', () => {
  expect(addDays('2026-12-31', 3)).toBe('2027-01-03');
  expect(addDays('2028-02-28', 1)).toBe('2028-02-29');
  expect(
    buildAttention([], [item('new-year', '2027-01-02')], '2026-12-31'),
  ).toHaveLength(1);
});
it('makes partial completion and unavailable assignees clear before acting', () => {
  const multi = row('multi', '2026-10-23');
  multi.occurrence!.assignee_ids = ['A', 'B'];
  multi.occurrence!.member_progress.A.status = 'completed';
  multi.assignee_unavailable = ['B'];
  expect(taskCaption(multi, 'A')).toContain('你已完成，等待其他成员');
  expect(taskCaption(multi, 'A')).toContain('负责人已停用');
  expect(taskCaption(multi, 'B')).toContain('每人完成自己的部分');
});
