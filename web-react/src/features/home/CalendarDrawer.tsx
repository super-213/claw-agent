import { useCallback, useEffect, useId, useRef, useState, type PointerEvent, type ReactNode } from 'react';
import { CalendarDays, X } from 'lucide-react';
import { useDialog } from '../../components/ui/useDialog';
import './calendar-drawer.css';

// Keep the edge recognizer separate from the page: vertical scrolling and board
// gestures elsewhere on the workbench must retain their normal behavior.
export function CalendarDrawer({ open, onOpen, onClose, children }: {
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
  children: (dismiss: () => void) => ReactNode;
}) {
  const id = useId();
  const [preview, setPreview] = useState(false);
  const backdrop = useRef<HTMLDivElement>(null);
  const frame = useRef(0);
  const position = useRef<number | null>(null);
  const velocity = useRef(0);
  const suppressClick = useRef(false);
  const drag = useRef<{ x: number; y: number; start: number; last: number; time: number; locked: boolean; opening: boolean; pointer: number } | null>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  const finish = useRef<(() => void) | null>(null);
  const { ref, dismiss } = useDialog(open, () => {
    settle(width(), () => { setPreview(false); closeRef.current(); });
  });
  const width = useCallback(() => ref.current?.getBoundingClientRect().width || Math.min(380, window.innerWidth - 44), [ref]);
  const paint = useCallback(() => {
    const x = position.current ?? width();
    if (ref.current) ref.current.style.transform = `translateX(${x}px)`;
    if (backdrop.current) backdrop.current.style.backgroundColor = `rgb(21 22 23 / ${0.44 * (1 - x / width())})`;
  }, [ref, width]);
  const settle = useCallback((target: number, done?: () => void) => {
    window.cancelAnimationFrame(frame.current);
    finish.current = done || null;
    const complete = () => {
      position.current = target;
      velocity.current = 0;
      paint();
      const callback = finish.current;
      finish.current = null;
      callback?.();
    };
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) { complete(); return; }
    let last = performance.now();
    const tick = (now: number) => {
      const dt = Math.min(0.025, (now - last) / 1000);
      last = now;
      const x = position.current ?? width();
      velocity.current += ((target - x) * 400 - velocity.current * 40) * dt;
      position.current = Math.max(0, Math.min(width(), x + velocity.current * dt));
      paint();
      if (Math.abs(target - position.current) < 0.5 && Math.abs(velocity.current) < 3) complete();
      else frame.current = requestAnimationFrame(tick);
    };
    frame.current = requestAnimationFrame(tick);
  }, [paint, width]);
  useEffect(() => {
    if (open) {
      if (!preview) { position.current = width(); paint(); }
      settle(0);
    }
  }, [open, preview, settle, width, paint]);
  useEffect(() => () => window.cancelAnimationFrame(frame.current), []);

  const down = (event: PointerEvent<HTMLElement>, opening: boolean) => {
    if (!event.isPrimary || event.button !== 0 || drag.current) return;
    if (opening && !window.matchMedia('(max-width: 1199px)').matches) return;
    window.cancelAnimationFrame(frame.current);
    finish.current = null;
    suppressClick.current = false;
    if (position.current === null || (opening && !preview)) position.current = opening ? width() : 0;
    velocity.current = 0;
    drag.current = { x: event.clientX, y: event.clientY, start: position.current, last: event.clientX, time: event.timeStamp, locked: false, opening, pointer: event.pointerId };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const move = (event: PointerEvent<HTMLElement>) => {
    const state = drag.current;
    if (!state || state.pointer !== event.pointerId) return;
    const dx = event.clientX - state.x;
    const dy = event.clientY - state.y;
    if (!state.locked) {
      if (Math.max(Math.abs(dx), Math.abs(dy)) < 8) return;
      if (Math.abs(dy) >= Math.abs(dx) || (state.opening && dx >= 0)) { drag.current = null; return; }
      state.locked = true;
      if (state.opening) setPreview(true);
    }
    velocity.current = (event.clientX - state.last) / Math.max(1, event.timeStamp - state.time) * 1000;
    position.current = Math.max(0, Math.min(width(), state.start + dx));
    state.last = event.clientX;
    state.time = event.timeStamp;
    paint();
  };
  const end = (event: PointerEvent<HTMLElement>, cancelled = false) => {
    const state = drag.current;
    if (!state || state.pointer !== event.pointerId) return;
    drag.current = null;
    if (!state.locked) return;
    suppressClick.current = true;
    if (event.timeStamp - state.time > 100) velocity.current = 0;
    const projected = (position.current ?? width()) + velocity.current * 0.18;
    const show = cancelled ? !state.opening : projected < width() * (state.opening ? 0.8 : 0.5);
    if (show) {
      if (state.opening) onOpen();
      else settle(0);
    } else if (state.opening) settle(width(), () => setPreview(false));
    else dismiss();
  };
  const gestures = {
    onPointerMove: move,
    onPointerUp: (event: PointerEvent<HTMLElement>) => end(event),
    onPointerCancel: (event: PointerEvent<HTMLElement>) => end(event, true),
  };
  const visible = open || preview;
  return <>
    <button type="button" className="home-calendar-edge" aria-label="打开家庭日历" aria-haspopup="dialog" aria-expanded={open}
      onClick={() => { if (!suppressClick.current && !preview) onOpen(); }} onPointerDown={(event) => down(event, true)} {...gestures}>
      <span aria-hidden="true" />
    </button>
    <div className="home-calendar-drawer-backdrop" ref={backdrop} hidden={!visible} aria-hidden={!open}
      onClick={(event) => { if (open && event.target === event.currentTarget) dismiss(); }}>
      <div className="home-calendar-drawer" ref={ref}
        role={open ? 'dialog' : undefined} aria-modal={open || undefined} aria-labelledby={id} tabIndex={-1}>
        <header onPointerDown={(event) => { if (!(event.target as HTMLElement).closest('button')) down(event, false); }} {...gestures}>
          <h2 id={id}><CalendarDays size={20} aria-hidden="true" />家庭日历</h2>
          <button type="button" onClick={dismiss} aria-label="关闭家庭日历"><X size={21} /></button>
        </header>
        <div className="home-calendar-drawer-content">{visible && children(dismiss)}</div>
      </div>
    </div>
  </>;
}
