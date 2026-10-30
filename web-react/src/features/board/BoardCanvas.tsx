import { memo, useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';
import { GripHorizontal, Maximize2, Minus, Plus } from 'lucide-react';
import type { BoardView } from '../../api/board';
import { BoardNote } from './BoardNote';
import { boardTime } from './boardTime';
import { arrangeBoard, BOARD_PADDING, BOARD_WIDTH, boardLayoutKey, bringToFront, ensurePlacements, moveNote, NOTE_HEIGHT, NOTE_WIDTH, parseBoardLayout, placementInBoard, type BoardLayout, type NotePlacement } from './boardLayout';

const MOBILE_BOARD_QUERY = '(max-width: 767px), (hover: none) and (pointer: coarse)';

interface DragSession {
  id: string; pointerId: number; target: HTMLButtonElement; startX: number; startY: number;
  origin: NotePlacement; restore: NotePlacement; scrollX: number; scrollY: number; x: number; y: number; moved: boolean;
}
const CanvasNote = memo(function CanvasNote({ view, placement, dragging, activate, start, move, end, cancel, keyboard, onOpen, onPreview }: {
  view: BoardView; placement: NotePlacement; dragging: boolean;
  activate: (id: string) => void; start: (id: string, event: PointerEvent<HTMLButtonElement>) => void;
  move: (event: PointerEvent<HTMLButtonElement>) => void; end: (event: PointerEvent<HTMLButtonElement>) => void;
  cancel: () => void; keyboard: (id: string, event: KeyboardEvent<HTMLButtonElement>) => void;
  onOpen: (id: string) => void; onPreview: (id: string, assetId: string) => void;
}) {
  const title = view.post.title || '未命名便笺';
  const author = view.members.find(m => m.member_id === view.post.created_by)?.display_name || '家庭成员';
  return <div className={`board-canvas-note${dragging ? ' is-dragging' : ''}`} data-note-id={view.post.id}
    style={{ transform: `translate3d(${placement.x}px, ${placement.y}px, 0)`, zIndex: placement.z }}
    onPointerDownCapture={() => activate(view.post.id)} onFocusCapture={() => activate(view.post.id)}>
    <BoardNote view={view} onOpen={() => onOpen(view.post.id)} onPreview={asset => onPreview(view.post.id, asset)} dragHandle={
      <button type="button" className="board-note-drag-handle" aria-label={`移动便笺：${title}`} aria-pressed={dragging}
        title="拖动摆放，方向键微调，Shift 加速；Esc 取消拖动" onClick={e => e.stopPropagation()}
        onPointerDown={e => start(view.post.id, e)} onPointerMove={move} onPointerUp={end}
        onPointerCancel={cancel} onLostPointerCapture={cancel} onKeyDown={e => keyboard(view.post.id, e)}>
        <span>{author} {view.activity_kind === 'poll' ? '发起投票' : view.activity_kind === 'relay' ? '发起接龙' : '留言'}</span><GripHorizontal size={16} aria-hidden="true" /><time dateTime={view.post.published_at || view.post.created_at}>{boardTime(view.post.published_at || view.post.created_at, view.timezone)}</time>
      </button>
    } />
  </div>;
});

export function BoardCanvas({ rows, userId, onOpen, onPreview }: {
  rows: BoardView[]; userId: string; onOpen: (id: string) => void; onPreview: (id: string, assetId: string) => void;
}) {
  const [mobile, setMobile] = useState(() => window.matchMedia?.(MOBILE_BOARD_QUERY).matches || false);
  const overview = mobile;
  const viewport = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(960);
  const [height, setHeight] = useState(520);
  const [zoom, setZoom] = useState<number | null>(null);
  const [layout, setLayout] = useState<BoardLayout>(() => { try { return parseBoardLayout(localStorage.getItem(boardLayoutKey(userId))); } catch { return {}; } });
  const layoutRef = useRef(layout); layoutRef.current = layout;
  const visibleIds = rows.map(row => row.post.id).join('\0');
  const placements = ensurePlacements(layout, rows.map(row => row.post.id));
  const [dragging, setDragging] = useState<string | null>(null);
  const drag = useRef<DragSession | null>(null);
  const frame = useRef<number | null>(null);
  const pan = useRef<{ id: number; x: number; y: number; left: number; top: number } | null>(null);
  const [message, setMessage] = useState('');
  const isCanvas = !overview;
  const fittedScale = Math.max(.01, Math.min(1, width / BOARD_WIDTH, height / (NOTE_HEIGHT + 2 * BOARD_PADDING)));
  const scale = zoom ?? fittedScale;
  // Every visible pixel belongs to the logical board, including the area freed
  // by zooming out. Fixed logical dimensions left an unreachable strip at right.
  const requiredWidth = Math.max(BOARD_WIDTH, width / scale);
  const requiredHeight = Math.max(NOTE_HEIGHT + 2 * BOARD_PADDING, height / scale);
  const scene = useRef({ width: requiredWidth, height: requiredHeight });
  // The logical board is bounded during a gesture. Moving a paper must not
  // enlarge the surface or change the scale beneath the pointer.
  if (!drag.current) scene.current = { width: requiredWidth, height: requiredHeight };
  const extentWidth = scene.current.width;
  const extentHeight = scene.current.height;
  const scaleRef = useRef(scale); scaleRef.current = scale;

  const update = useCallback((next: BoardLayout, persist = true) => {
    layoutRef.current = next; setLayout(next);
    if (persist) {
      try { localStorage.setItem(boardLayoutKey(userId), JSON.stringify(next)); }
      catch { setMessage('摆放已更新，当前浏览器无法保存位置。'); }
    }
  }, [userId]);
  useEffect(() => {
    const next = ensurePlacements(layoutRef.current, visibleIds ? visibleIds.split('\0') : []);
    if (next !== layoutRef.current) update(next);
  }, [visibleIds, update]);
  useEffect(() => {
    const query = window.matchMedia(MOBILE_BOARD_QUERY);
    const changed = () => { setMobile(query.matches); setZoom(null); };
    query.addEventListener('change', changed);
    return () => query.removeEventListener('change', changed);
  }, []);
  useEffect(() => {
    const node = viewport.current;
    if (!node || !isCanvas) return;
    const measure = () => {
      if (!node.clientWidth) return;
      if (!mobile) {
        const top = node.getBoundingClientRect().top + window.scrollY;
        const more = node.closest('.board-desk')?.querySelector<HTMLElement>(':scope > .board-load-more');
        const bottom = 12 + 28 + 8 + (more ? more.offsetHeight + 22 : 0);
        const available = Math.max(180, Math.min(1000, Math.floor(window.innerHeight - top - bottom)));
        node.style.setProperty('--board-available-height', `${available}px`);
      } else node.style.removeProperty('--board-available-height');
      setWidth(node.clientWidth); setHeight(node.clientHeight);
    };
    measure();
    window.addEventListener('resize', measure);
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure);
    for (const element of [node, node.closest('.home-today-main'), document.querySelector('.home-command'), document.querySelector('.home-topbar'), document.querySelector('.home-dashboard-feedback')]) {
      if (element) observer?.observe(element);
    }
    return () => { observer?.disconnect(); window.removeEventListener('resize', measure); };
  }, [isCanvas, mobile]);
  useEffect(() => () => { if (frame.current !== null) window.cancelAnimationFrame(frame.current); }, []);
  const activate = useCallback((id: string) => {
    const next = bringToFront(layoutRef.current, id);
    if (next !== layoutRef.current) update(next);
  }, [update]);
  const tick = useCallback(function trackDrag() {
    frame.current = null;
    const session = drag.current;
    const node = viewport.current;
    if (!session || !node) return;
    if (!session.moved && Math.hypot(session.x - session.startX, session.y - session.startY) < 5) return;
    if (!session.moved) { session.moved = true; setDragging(session.id); }
    const bounds = node.getBoundingClientRect();
    const edge = (point: number, low: number, high: number) => point < low + 28 ? -10 : point > high - 28 ? 10 : 0;
    const dx = edge(session.x, bounds.left, bounds.right);
    const dy = edge(session.y, bounds.top, bounds.bottom);
    if (session.x >= bounds.left - 24 && session.x <= bounds.right + 24 && session.y >= bounds.top - 24 && session.y <= bounds.bottom + 24) node.scrollBy(dx, dy);
    const next = moveNote(layoutRef.current, session.id,
      session.origin.x + (session.x - session.startX + node.scrollLeft - session.scrollX) / scaleRef.current,
      session.origin.y + (session.y - session.startY + node.scrollTop - session.scrollY) / scaleRef.current, scene.current);
    update(next, false);
    if (dx || dy) frame.current = window.requestAnimationFrame(trackDrag);
  }, [update]);
  const cancel = useCallback(() => {
    const session = drag.current;
    if (!session) return;
    drag.current = null;
    if (frame.current !== null) { window.cancelAnimationFrame(frame.current); frame.current = null; }
    update(moveNote(layoutRef.current, session.id, session.restore.x, session.restore.y));
    setDragging(null);
    if (session.target.hasPointerCapture?.(session.pointerId)) session.target.releasePointerCapture(session.pointerId);
    setMessage('已取消移动。');
  }, [update]);
  const start = useCallback((id: string, event: PointerEvent<HTMLButtonElement>) => {
    if (event.button !== 0 || !event.isPrimary || drag.current) return;
    const node = viewport.current;
    const stored = layoutRef.current[id];
    if (!node || !stored) return;
    const origin = placementInBoard(stored, scene.current);
    event.preventDefault(); event.stopPropagation();
    event.currentTarget.focus({ preventScroll: true });
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragging(id);
    drag.current = { id, pointerId: event.pointerId, target: event.currentTarget, startX: event.clientX, startY: event.clientY,
      origin, restore: stored, scrollX: node.scrollLeft, scrollY: node.scrollTop, x: event.clientX, y: event.clientY, moved: false };
  }, []);
  const move = useCallback((event: PointerEvent<HTMLButtonElement>) => {
    if (!drag.current || drag.current.pointerId !== event.pointerId) return;
    drag.current.x = event.clientX; drag.current.y = event.clientY;
    if (frame.current === null) frame.current = window.requestAnimationFrame(tick);
  }, [tick]);
  const end = useCallback((event: PointerEvent<HTMLButtonElement>) => {
    const session = drag.current;
    if (!session || session.pointerId !== event.pointerId) return;
    session.x = event.clientX; session.y = event.clientY;
    if (frame.current !== null) { window.cancelAnimationFrame(frame.current); frame.current = null; }
    tick();
    if (frame.current !== null) { window.cancelAnimationFrame(frame.current); frame.current = null; }
    drag.current = null; setDragging(null); update(layoutRef.current);
    if (session.target.hasPointerCapture(event.pointerId)) session.target.releasePointerCapture(event.pointerId);
    if (session.moved) setMessage('便笺位置已保存。');
  }, [tick, update]);
  const keyboard = useCallback((id: string, event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === 'Escape' && drag.current) { event.preventDefault(); event.stopPropagation(); cancel(); return; }
    const direction: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
    if (!direction[event.key]) return;
    event.preventDefault(); event.stopPropagation();
    const stored = layoutRef.current[id];
    if (!stored) return;
    const position = placementInBoard(stored, scene.current);
    const [dx, dy] = direction[event.key];
    const distance = event.shiftKey ? 40 : 10;
    update(moveNote(layoutRef.current, id, position.x + dx * distance, position.y + dy * distance, scene.current));
    setMessage('便笺位置已保存。');
  }, [cancel, update]);
  const fit = () => { setZoom(null); viewport.current?.scrollTo(0, 0); };
  return <div className={`board-layout${overview ? ' is-overview' : ''}`}>
    {isCanvas && <div className="board-layout-toolbar">
      <div className="board-canvas-tools">
        <button type="button" aria-label="缩小画布" disabled={scale <= .35 || !!dragging} onClick={() => setZoom(Math.max(.35, +(scale - .1).toFixed(2)))}><Minus size={15} /></button>
        <output aria-label="画布缩放比例">{Math.round(scale * 100)}%</output>
        <button type="button" aria-label="放大画布" disabled={scale >= 1.25 || !!dragging} onClick={() => setZoom(Math.min(1.25, +(scale + .1).toFixed(2)))}><Plus size={15} /></button>
        <button type="button" aria-label="完整显示留言板" title="完整显示" onClick={fit}><Maximize2 size={15} /></button>
        <button type="button" onClick={() => { cancel(); const columns = Math.max(1, Math.min(3, Math.floor((width / scale - BOARD_PADDING) / (NOTE_WIDTH + BOARD_PADDING)))); update({ ...layoutRef.current, ...arrangeBoard(rows.map(r => r.post.id), columns) }); setMessage('已整理当前便笺。'); viewport.current?.scrollTo(0, 0); }}>整理</button>
      </div>
    </div>}
    {overview ? <div className="board-overview-grid">{rows.map(row => <BoardNote key={row.post.id} compact view={row} onOpen={() => onOpen(row.post.id)} onPreview={asset => onPreview(row.post.id, asset)} />)}</div> : <div ref={viewport} className="board-canvas-viewport" role="region" aria-label="可自由摆放的留言板画布" tabIndex={0}
      onPointerDown={event => {
        if (event.pointerType !== 'mouse' || event.button !== 0 || (event.target as HTMLElement).closest('.board-canvas-note')) return;
        event.preventDefault();
        event.currentTarget.setPointerCapture(event.pointerId);
        pan.current = { id: event.pointerId, x: event.clientX, y: event.clientY, left: event.currentTarget.scrollLeft, top: event.currentTarget.scrollTop };
      }}
      onPointerMove={event => {
        if (pan.current?.id !== event.pointerId) return;
        event.currentTarget.scrollLeft = pan.current.left - (event.clientX - pan.current.x);
        event.currentTarget.scrollTop = pan.current.top - (event.clientY - pan.current.y);
      }}
      onPointerUp={event => { if (pan.current?.id === event.pointerId) { pan.current = null; event.currentTarget.releasePointerCapture(event.pointerId); } }}
      onPointerCancel={() => { pan.current = null; }} onLostPointerCapture={() => { pan.current = null; }}>
      <div className="board-canvas-size" style={{ width: Math.floor(extentWidth * scale), height: Math.floor(extentHeight * scale) }}>
        <div className="board-canvas-world" style={{ width: extentWidth, height: extentHeight, transform: `scale(${scale})` }}>
          {rows.map(row => <CanvasNote key={row.post.id} view={row} placement={placementInBoard(placements[row.post.id], scene.current)} dragging={dragging === row.post.id} activate={activate} start={start} move={move} end={end} cancel={cancel} keyboard={keyboard} onOpen={onOpen} onPreview={onPreview} />)}
        </div>
      </div>
    </div>}
    <span className="sr-only" role="status">{message}</span>
  </div>;
}
