import { useCallback, useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError } from '../../api/client';
import { useAppStore } from '../../stores/appStore';
import { cardAdapter } from './registry';
import { announceResourceChange, forgetCardEdit, forgetCardSubmission, readCardSubmission, writeCardSubmission } from './state';
import type { CardContext, CardView, InteractiveCardRef } from './types';
import './interactive-cards.css';

export function InteractiveCardHost({ reference, context = { surface: 'chat' } }: {
  reference: InteractiveCardRef; context?: CardContext;
}) {
  const adapter = cardAdapter(reference);
  const owner = useAppStore((state) => state.currentUser?.id);
  if (!adapter) return <aside className="interactive-card card-fallback">当前版本暂不支持这张卡片，请查看文字结果。</aside>;
  if (!owner) return <aside className="interactive-card card-fallback">登录后可查看此记录。</aside>;
  return <BoundCard key={`${owner}:${reference.card_id}:${context.sessionId || ''}`} reference={reference} context={context} owner={owner} />;
}

function BoundCard({ reference, context, owner }: { reference: InteractiveCardRef; context: CardContext; owner: string }) {
  const adapter = cardAdapter(reference)!;
  const client = useQueryClient();
  const key = ['interactive-cards', owner, reference.resource.type, reference.resource.id, reference.resource.instance_id || '', context.sessionId || ''];
  const query = useQuery({ queryKey: key, queryFn: () => adapter.load(reference, context), retry: false,
    staleTime: 0, refetchOnWindowFocus: true });
  const refetch = query.refetch;
  const editKey = `${owner}:${reference.card_id}`;
  const [busy, setBusy] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState(() => readCardSubmission(editKey) ? '上次保存结果待核实，请使用原请求重试。' : '');
  const [uncertain, setUncertain] = useState(() => !!readCardSubmission(editKey));
  const [savedSequence, setSavedSequence] = useState(0);
  const pending = useRef(readCardSubmission(editKey) || null);
  const mounted = useRef(true);
  const busyRef = useRef(false);
  const retryRef = useRef<() => void>(() => undefined);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  const refresh = useCallback(async () => {
    setVerifying(true);
    const result = await refetch();
    if (mounted.current) setVerifying(!!result.error);
  }, [refetch]);

  useEffect(() => {
    if (!query.data) return;
    const observed = performance.now();
    const server = Date.parse(query.data.server_now);
    const check = () => {
      if (document.visibilityState === 'hidden') return;
      void refresh();
    };
    const next = Date.parse(query.data.next_transition_at || '');
    // Use a monotonic elapsed duration, so changing the device's wall clock
    // cannot extend a previously observed server capability window.
    const wait = Number.isFinite(next) && next > server ? Math.max(20, Math.min(60_000, next - server - (performance.now() - observed) + 20)) : 60_000;
    const timer = window.setTimeout(check, wait);
    const changed = (event: Event) => {
      const detail = (event as CustomEvent<{ resource_type?: string; resource_id?: string; resource_ids?: string[] }>).detail;
      const resource = query.data.resource;
      if (event.type === 'task_changed' && !['family_task', 'task_draft'].includes(reference.resource.type)) return;
      if (detail?.resource_type && detail.resource_type !== reference.resource.type && detail.resource_type !== resource.type) return;
      const ids = detail?.resource_ids || (detail?.resource_id ? [detail.resource_id] : []);
      if (ids.length && !ids.includes(reference.resource.id) && !ids.includes(resource.id)) return;
      void client.invalidateQueries({ queryKey: ['interactive-cards', owner], predicate: q => {
        const value = q.state.data as CardView | undefined;
        return q.queryKey[2] === reference.resource.type && q.queryKey[3] === reference.resource.id
          || value?.resource.type === resource.type && value.resource.id === resource.id;
      } });
    };
    const visible = () => { if (document.visibilityState !== 'hidden') check(); };
    window.addEventListener('resource_changed', changed);
    window.addEventListener('task_changed', changed);
    window.addEventListener('focus', check);
    window.addEventListener('online', check);
    document.addEventListener('visibilitychange', visible);
    return () => {
      clearTimeout(timer);
      window.removeEventListener('resource_changed', changed);
      window.removeEventListener('task_changed', changed);
      window.removeEventListener('focus', check);
      window.removeEventListener('online', check);
      document.removeEventListener('visibilitychange', visible);
    };
  }, [query.data, query.dataUpdatedAt, client, owner, refresh, reference.resource.type, reference.resource.id]);

  const submit = async (action: unknown): Promise<CardView> => {
    if (busyRef.current) throw new Error('正在保存，请稍候。');
    if (!window.navigator.onLine) throw new Error('当前离线，修改尚未保存。');
    const signature = JSON.stringify(action);
    if (pending.current && pending.current.signature !== signature) throw new Error('请先核实上次保存的结果。');
    const attempt = pending.current || { id: window.crypto.randomUUID(), action, signature };
    pending.current = attempt;
    writeCardSubmission(editKey, attempt);
    busyRef.current = true;
    setBusy(true); setError('');
    try {
      const result = await adapter.submit(reference, action, context, attempt.id);
      if (useAppStore.getState().currentUser?.id !== owner) throw new Error('账号已切换。');
      pending.current = null;
      forgetCardSubmission(editKey, attempt.id);
      if (mounted.current) {
        setUncertain(false);
        forgetCardEdit(editKey);
        setSavedSequence(value => value + 1);
        client.setQueryData(key, result);
        announceResourceChange(result.resource);
        adapter.invalidate?.({ ...reference, resource: result.resource, mode: result.mode });
        if (result.resource.id !== reference.resource.id) announceResourceChange(reference.resource);
        void query.refetch();
      }
      return result;
    } catch (caught) {
      const known = caught instanceof ApiError && caught.status >= 400;
      if (known) { pending.current = null; forgetCardSubmission(editKey, attempt.id); }
      if (mounted.current) {
        setUncertain(!known);
        setError(known ? (caught as Error).message : '保存结果待核实，请点击“核实并重试”；不会重复创建。');
        if (known) void refresh();
      }
      throw caught;
    } finally {
      busyRef.current = false;
      if (mounted.current) setBusy(false);
    }
  };
  retryRef.current = () => { if (pending.current) void submit(pending.current.action).catch(() => undefined); };

  // Do not keep private data visible after its latest authorized read fails.
  if (query.isError && query.error instanceof ApiError && [401, 403, 404].includes(query.error.status)) {
    return <aside className="interactive-card card-fallback" role="status">该记录已不可访问。</aside>;
  }
  if (!query.data) return <aside className="interactive-card card-fallback" role="status">
    {query.isError ? '暂时无法读取这张卡片。' : '正在读取最新记录…'}
    {query.isError && <button type="button" onClick={() => void refresh()}>重新读取</button>}
  </aside>;
  return adapter.render({ view: query.data, reference, context, editKey,
    submit, busy, verifying: verifying || !!query.error, uncertain, error,
    savedSequence, retry: () => retryRef.current(), refresh: () => void refresh() });
}
