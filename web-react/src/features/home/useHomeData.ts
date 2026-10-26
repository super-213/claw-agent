import { useEffect } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { homeApi, type InventoryLocation } from '../../api/home';
import { tasksApi, type TaskRow } from '../../api/tasks';
import { useAppStore } from '../../stores/appStore';

async function attentionTasks() {
  const members = await tasksApi.members();
  // The first response supplies the household date, including when the browser
  // is in another timezone. Follow every page before presenting a count.
  const first = await tasksApi.list({
    view: 'visible',
    status: 'open',
    actionable: true,
    temporal_type: 'timed',
    limit: '200',
  });
  const rows: TaskRow[] = [...first.items];
  let cursor = first.next_cursor;
  let complete = first.history_complete;
  while (cursor) {
    const next = await tasksApi.list({
      view: 'visible',
      status: 'open',
      actionable: true,
      temporal_type: 'timed',
      limit: '200',
      cursor,
    });
    rows.push(...next.items);
    cursor = next.next_cursor;
    complete &&= next.history_complete;
  }
  return {
    rows,
    actor: members.current_member_id,
    today: first.today,
    timezone: first.timezone,
    historyComplete: complete,
  };
}
export function useHomeData() {
  const user = useAppStore((s) => s.currentUser?.id);
  const client = useQueryClient();
  const inventory = (location: InventoryLocation) => ({
    queryKey: ['home', user, 'inventory', location],
    queryFn: () => homeApi.inventory(location),
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  });
  const fridge = useQuery(inventory('fridge'));
  const freezer = useQuery(inventory('freezer'));
  const pantry = useQuery(inventory('pantry'));
  const medicine = useQuery(inventory('medicine'));
  const tasks = useQuery({
    queryKey: ['home', user, 'attention'],
    queryFn: attentionTasks,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
    retry: false,
  });
  const memos = useQuery({
    queryKey: ['home', user, 'memos'],
    queryFn: () => tasksApi.summary({ view: 'mine' }),
    retry: false,
    refetchOnWindowFocus: true,
    refetchInterval: 60_000,
  });
  const refresh = () => client.invalidateQueries({ queryKey: ['home', user] });
  useEffect(() => {
    const refresh = () => {
      void client.invalidateQueries({ queryKey: ['home', user] });
    };
    window.addEventListener('task_changed', refresh);
    window.addEventListener('inventory_changed', refresh);
    return () => {
      window.removeEventListener('task_changed', refresh);
      window.removeEventListener('inventory_changed', refresh);
    };
  }, [client, user]);
  return {
    inventories: { fridge, freezer, pantry, medicine },
    tasks,
    memos,
    refresh,
  };
}
