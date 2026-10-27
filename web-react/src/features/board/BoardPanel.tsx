import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { Plus, StickyNote } from 'lucide-react';
import { ApiError } from '../../api/client';
import { boardApi, boardAssetUrl, type BoardView } from '../../api/board';
import { useAppStore } from '../../stores/appStore';
import { HomeDialog } from '../../components/ui/HomeDialog';
import { InteractiveCardHost } from '../interactive-cards/InteractiveCardHost';
import { isCardReference } from '../interactive-cards/registry';
import type { InteractiveCardRef } from '../interactive-cards/types';
import { BoardCanvas } from './BoardCanvas';
import './board.css';

const referenceFor = (view: BoardView): InteractiveCardRef => ({ type: 'interactive_card', schema_version: 1, kind: 'board_post', mode: view.mode, card_id: `workbench-${view.post.id}`, resource: view.resource });
export function BoardPanel({ active, panelSwitch }: { active: boolean; panelSwitch: ReactNode }) {
  const userId = useAppStore(s => s.currentUser?.id);
  const [params, setParams] = useSearchParams();
  const client = useQueryClient();
  const [expiredIds, setExpiredIds] = useState<Set<string>>(() => new Set());
  const [selected, setSelected] = useState<string | null>(params.get('post'));
  const [editor, setEditor] = useState<InteractiveCardRef | null>(null);
  const draftKey = `claw.board.draft.v1.${userId}`;
  const pendingDraft = useRef<InteractiveCardRef | null>((() => { try { const value: unknown = JSON.parse(localStorage.getItem(draftKey) || 'null'); return isCardReference(value) && value.kind === 'board_post' && value.resource.type === 'board_post_draft' ? value : null; } catch { return null; } })());
  const [image, setImage] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState('');
  const creation = useRef<string | null>(null);
  const query = useInfiniteQuery({ queryKey: ['board', userId], queryFn: ({ pageParam }) => boardApi.list(pageParam), initialPageParam: null as string | null,
    getNextPageParam: result => result.next_cursor, enabled: active && !!userId, retry: false, refetchOnWindowFocus: true, refetchInterval: active ? 30000 : false });
  const detail = useQuery({ queryKey: ['board-detail', userId, selected], queryFn: () => boardApi.get(selected!), enabled: active && !!selected,
    retry: false, refetchOnWindowFocus: true, refetchInterval: active ? 30000 : false });
  const serverClock = useRef<{ data?: typeof query.data; server: number; observed: number }>({ server: 0, observed: 0 });
  if (query.data && query.data !== serverClock.current.data) {
    serverClock.current = { data: query.data, server: Math.max(...query.data.pages.map(page => Date.parse(page.server_now))), observed: performance.now() };
  }
  const fetchedRows = query.data?.pages.flatMap(page => page.items) || [];
  const rows = fetchedRows.filter(row => !expiredIds.has(row.post.id));
  useEffect(() => { if (params.get('post')) setSelected(params.get('post')); }, [params]);
  useEffect(() => {
    const changed = (event: Event) => {
      if ((event as CustomEvent).detail?.resource_type?.startsWith('board_post')) {
        void client.invalidateQueries({ queryKey: ['board', userId] });
        void client.invalidateQueries({ queryKey: ['board-detail', userId] });
        setImage(null);
        if ((event as CustomEvent).detail?.resource_type === 'board_post') { pendingDraft.current = null; try { localStorage.removeItem(draftKey); } catch { /* Optional preference. */ } }
      }
    };
    window.addEventListener('resource_changed', changed);
    return () => window.removeEventListener('resource_changed', changed);
  }, [client, userId, draftKey]);
  useEffect(() => {
    if (!active || !query.data) return;
    const observed = serverClock.current.observed;
    const server = serverClock.current.server;
    const observedRows = [...query.data.pages.flatMap(page => page.items), ...(detail.data ? [detail.data] : [])];
    const now = () => server + performance.now() - observed;
    setExpiredIds(current => new Set([...current].filter(id => !observedRows.some(row => row.post.id === id && (!row.post.expires_at || Date.parse(row.post.expires_at) > now())))));
    const expire = () => {
      const ended = observedRows.filter(row => row.post.expires_at && Date.parse(row.post.expires_at) <= now()).map(row => row.post.id);
      if (ended.length) {
        setExpiredIds(current => new Set([...current, ...ended]));
        setImage(null);
      }
      void query.refetch();
      if (selected) void detail.refetch();
    };
    const deadlines = observedRows.map(row => Date.parse(row.post.expires_at || '')).filter(Number.isFinite);
    if (!deadlines.length) return;
    const timer = window.setTimeout(expire, Math.max(20, Math.min(30000, Math.min(...deadlines) - now() + 20)));
    return () => clearTimeout(timer);
  }, [active, query.data, query.dataUpdatedAt, detail.data, selected]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (detail.isError) setImage(null); }, [detail.isError]);
  const create = async () => {
    if (creating) return;
    if (pendingDraft.current) { setEditor(pendingDraft.current); return; }
    setCreating(true); setError('');
    creation.current ||= window.crypto.randomUUID();
    try {
      const result = await boardApi.createDraft(creation.current);
      if (useAppStore.getState().currentUser?.id !== userId) return;
      creation.current = null; pendingDraft.current = referenceFor(result); setEditor(pendingDraft.current);
      try { localStorage.setItem(draftKey, JSON.stringify(pendingDraft.current)); } catch { /* Keep the active editor usable. */ }
    } catch (caught) {
      if (caught instanceof ApiError) creation.current = null;
      setError(caught instanceof ApiError ? caught.message : '草稿创建结果待核实，请再次点击“写便笺”；将沿用原请求核实。');
    } finally { setCreating(false); }
  };
  const closeDetail = () => {
    setSelected(null); setImage(null);
    if (params.has('post')) { const next = new URLSearchParams(params); next.delete('post'); setParams(next, { replace: true }); }
  };
  const openNote = useCallback((id: string) => setSelected(id), []);
  const previewNote = useCallback((id: string, assetId: string) => { setSelected(id); setImage(assetId); }, []);
  const denied = query.isError && query.error instanceof ApiError && [401, 403, 404].includes(query.error.status);
  return <section className="board-panel" aria-label="留言板" hidden={!active}>
    <div className="board-toolbar">
      <div className="board-toolbar-heading">{panelSwitch}<button type="button" className="board-primary" disabled={creating} onClick={() => void create()}><Plus size={16} />{creating ? '准备中…' : '写便笺'}</button></div>

    </div>
    {error && <p role="alert" className="board-error">{error}</p>}
    {query.isError && <p role="alert" className="board-error">{denied ? '当前无法访问留言板。' : '便笺暂时无法更新，请重试。'}<button type="button" onClick={() => void query.refetch()}>重新读取</button></p>}
    <div className="board-desk">
      {query.isPending && <p role="status">正在读取便笺…</p>}
      {!query.isPending && !query.isError && !rows.length && <div className="board-empty"><StickyNote size={32} strokeWidth={1.25} /><h3>还没有便笺</h3><p>这里展示自己创建、@ 自己和 @ 所有人的便笺。</p><button type="button" onClick={() => void create()}>写第一张便笺</button></div>}
      {!denied && !!rows.length && <BoardCanvas key={userId} userId={userId || 'guest'} rows={rows} onOpen={openNote} onPreview={previewNote} />}
      {query.hasNextPage && <button className="board-load-more" type="button" disabled={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>查看更多便笺</button>}
    </div>
    {active && selected && <HomeDialog className="board-dialog" title="便笺详情" onClose={closeDetail} wide>
      {detail.isError ? <p role="alert">{detail.error instanceof ApiError && [401, 403, 404].includes(detail.error.status) ? '该便笺已不可访问。' : '暂时无法读取便笺。'}<button type="button" onClick={() => void detail.refetch()}>重试</button></p> : !detail.data ? <p role="status">正在读取便笺…</p> : <>
        <InteractiveCardHost reference={referenceFor(detail.data)} context={{ surface: 'workbench_board' }} />
      </>}
    </HomeDialog>}
    {active && editor && <HomeDialog className="board-dialog" title="写便笺" onClose={() => setEditor(null)} wide><InteractiveCardHost reference={editor} context={{ surface: 'workbench_board' }} /><button type="button" className="board-load-more" onClick={() => { pendingDraft.current = null; try { localStorage.removeItem(draftKey); } catch { /* Optional preference. */ } setEditor(null); }}>放弃此草稿</button></HomeDialog>}
    {active && image && <HomeDialog className="board-dialog" title="便笺图片" onClose={() => setImage(null)} wide><img className="board-full-image" src={boardAssetUrl(image)} alt="便笺图片预览" /></HomeDialog>}
  </section>;
}
