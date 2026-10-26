import type { HomeInventoryItem } from '../../api/types';
import type { TaskRow } from '../../api/tasks';

export const locations = {
  fridge: '冰箱',
  freezer: '冷冻室',
  pantry: '食品柜',
  medicine: '药箱',
} as const;
export const activeInventory = (item: HomeInventoryItem) =>
  ['available', 'low'].includes(item.status || 'available');
export function addDays(day: string, amount: number) {
  const date = new Date(`${day}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + amount);
  return date.toISOString().slice(0, 10);
}
export function expiryLabel(item: HomeInventoryItem, today: string) {
  if (!item.expires_at) return '未记录到期日';
  if (item.expires_at < today) return `已过期 · ${item.expires_at}`;
  if (item.expires_at === today) return '今天到期';
  if (item.expires_at === addDays(today, 1)) return '明天到期';
  return `${item.expires_at} 到期`;
}
export function taskCaption(row: TaskRow, actor: string | null) {
  const occurrence = row.occurrence;
  const ids = occurrence?.assignee_ids || row.task.assignee_ids;
  const mineDone =
    actor && occurrence?.member_progress[actor]?.status === 'completed';
  const ownership =
    mineDone && occurrence?.status === 'open'
      ? '你已完成，等待其他成员'
      : ids.includes(actor || '')
        ? ids.length > 1 && occurrence?.completion_mode === 'all'
          ? '每人完成自己的部分'
          : '由我处理'
        : ids.length
          ? '由其他成员处理'
          : '等待认领';
  return `${row.overdue ? '已逾期 · ' : ''}${occurrence?.due_date || '无日期'} · ${ownership}${row.assignee_unavailable.length ? ' · 负责人已停用' : ''}`;
}
export type Attention = {
  id: string;
  title: string;
  date: string;
  priority: number;
} & (
  { kind: 'task'; row: TaskRow } | { kind: 'item'; item: HomeInventoryItem }
);
export function buildAttention(
  rows: TaskRow[],
  items: HomeInventoryItem[],
  today: string,
): Attention[] {
  const seen = new Set<string>();
  const tasks: Attention[] = rows
    .filter((row) => {
      const key = row.occurrence?.id || row.task.id;
      if (seen.has(key)) return false;
      seen.add(key);
      return (
        row.task.actionable &&
        row.task.lifecycle === 'active' &&
        row.occurrence?.status === 'open' &&
        Boolean(row.occurrence.due_date && row.occurrence.due_date <= today)
      );
    })
    .map((row) => ({
      kind: 'task',
      row,
      id: `task-${row.occurrence!.id}`,
      title: row.occurrence!.title_snapshot || row.task.title,
      date: row.occurrence!.due_date!,
      priority: row.overdue ? 0 : 1,
    }));
  const inventory: Attention[] = items
    .filter(
      (item) =>
        activeInventory(item) &&
        item.expires_at &&
        item.expires_at <= addDays(today, 3),
    )
    .map((item) => ({
      kind: 'item',
      item,
      id: `item-${item.location}-${item.id}`,
      title: `${item.name}${item.quantity != null ? ` ${item.quantity}${item.unit || ''}` : ''}`,
      date: item.expires_at!,
      priority:
        item.expires_at! < today ? 0 : item.expires_at === today ? 1 : 2,
    }));
  return [...tasks, ...inventory].sort(
    (a, b) =>
      a.priority - b.priority ||
      a.date.localeCompare(b.date) ||
      a.id.localeCompare(b.id),
  );
}
