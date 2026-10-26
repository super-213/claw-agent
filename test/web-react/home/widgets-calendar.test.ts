import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { HomeWidgets } from '../../../web-react/src/features/home/HomeWidgets';
import {
  defaultWidgets,
  moveWidget,
  parseWidgetLayout,
  widgetStorageKey,
} from '../../../web-react/src/features/home/widgetLayout';
import {
  monthDays,
  shiftMonth,
} from '../../../web-react/src/features/home/calendarModel';

afterEach(() => {
  cleanup();
  localStorage.clear();
});
it('builds Monday-first real calendar dates across leap months and years', () => {
  const days = monthDays('2028-02');
  expect(days).toHaveLength(42);
  expect(days[0]).toBe('2028-01-31');
  expect(days).toContain('2028-02-29');
  expect(days[41]).toBe('2028-03-12');
  expect(shiftMonth('2026-12', 1)).toBe('2027-01');
  expect(shiftMonth('2027-01', -1)).toBe('2026-12');
});
it('restores corrupted layouts safely and preserves intentional empty layouts', () => {
  expect(parseWidgetLayout('bad')).toEqual(defaultWidgets);
  expect(parseWidgetLayout('[]')).toEqual([]);
  expect(
    parseWidgetLayout(
      '[{"kind":"today","size":"small"},{"kind":"today","size":"large"},{"kind":"future","size":"medium"},{"kind":"constructor","size":"small"}]',
    ),
  ).toEqual([{ kind: 'today', size: 'small' }]);
  const moved = moveWidget(defaultWidgets, 0, 3);
  expect(moved[3].kind).toBe('today');
  expect(defaultWidgets[0].kind).toBe('today');
  expect(moveWidget(defaultWidgets, 0, -1)).toBe(defaultWidgets);
});
const widgetBoard = (userId: string) =>
  React.createElement(HomeWidgets, {
    userId,
    items: [],
    inventoryReady: () => true,
    inventoryFailed: () => false,
    taskRows: [],
    actor: 'A',
    today: '2026-10-23',
    tasksReady: true,
    memoCount: 3,
    attentionCount: 0,
    onOpen: () => undefined,
    renderAttention: () => React.createElement('p', {}, '关注列表内容'),
  });
it('persists size, removal and keyboard reorder per account, and recovers removed widgets', () => {
  const view = render(widgetBoard('alice'));
  fireEvent.click(screen.getByRole('button', { name: '自定义', exact: true }));
  fireEvent.change(screen.getByLabelText('冰箱尺寸'), {
    target: { value: 'large' },
  });
  fireEvent.keyDown(
    screen.getByRole('button', { name: '移动冰箱，使用方向键排序' }),
    { key: 'ArrowLeft' },
  );
  fireEvent.click(screen.getByRole('button', { name: '移除药箱' }));
  const stored = parseWidgetLayout(
    localStorage.getItem(widgetStorageKey('alice')),
  );
  expect(stored[0]).toEqual({ kind: 'fridge', size: 'large' });
  expect(stored.some((w) => w.kind === 'medicine')).toBe(false);
  expect(localStorage.getItem(widgetStorageKey('bob'))).toBeNull();
  view.unmount();
  render(widgetBoard('alice'));
  expect(
    document
      .querySelector('[data-widget-kind="fridge"]')
      ?.classList.contains('widget-large'),
  ).toBe(true);
  expect(document.querySelector('[data-widget-kind="medicine"]')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '自定义', exact: true }));
  fireEvent.click(
    screen.getByRole('button', { name: '添加组件', exact: true }),
  );
  fireEvent.click(screen.getByRole('button', { name: /药箱 添加/ }));
  expect(
    parseWidgetLayout(localStorage.getItem(widgetStorageKey('alice'))).some(
      (w) => w.kind === 'medicine',
    ),
  ).toBe(true);
});
