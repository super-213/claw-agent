import { useEffect, useRef, type PointerEvent, type RefObject } from 'react';

export function useSheetDrag(ref: RefObject<HTMLElement>, dismiss: () => void, enabled = true) {
  const frame = useRef(0);
  const position = useRef(0);
  const velocity = useRef(0);
  const drag = useRef<{ start: number; last: number; time: number } | null>(null);
  useEffect(() => () => window.cancelAnimationFrame(frame.current), []);
  const paint = () => { if (ref.current) ref.current.style.transform = `translateY(${Math.max(0, position.current)}px)`; };
  const settle = (target: number) => {
    window.cancelAnimationFrame(frame.current);
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      position.current = 0; paint(); if (target) dismiss(); return;
    }
    let last = window.performance.now();
    const tick = (now: number) => {
      const dt = Math.min(0.025, (now - last) / 1000); last = now;
      velocity.current += ((target - position.current) * 400 - velocity.current * 38) * dt;
      position.current += velocity.current * dt; paint();
      if (Math.abs(target - position.current) < 0.5 && Math.abs(velocity.current) < 3) {
        position.current = target; paint(); if (target) dismiss();
      } else frame.current = window.requestAnimationFrame(tick);
    };
    frame.current = window.requestAnimationFrame(tick);
  };
  const onPointerDown = (event: PointerEvent<HTMLElement>) => {
    if (!enabled || !event.isPrimary || event.button !== 0 || event.clientX < 24 || event.clientX > window.innerWidth - 24) return;
    window.cancelAnimationFrame(frame.current);
    drag.current = { start: event.clientY - position.current, last: event.clientY, time: event.timeStamp };
    velocity.current = 0;
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const onPointerMove = (event: PointerEvent<HTMLElement>) => {
    const state = drag.current;
    if (!state) return;
    velocity.current = (event.clientY - state.last) / Math.max(1, event.timeStamp - state.time) * 1000;
    position.current = Math.max(0, event.clientY - state.start);
    state.last = event.clientY; state.time = event.timeStamp; paint();
  };
  const end = (event: PointerEvent<HTMLElement>, cancelled: boolean) => {
    const state = drag.current;
    drag.current = null;
    if (!state) return;
    if (event.timeStamp - state.time > 100) velocity.current = 0;
    const close = !cancelled && position.current > 12 && (position.current > 110 || velocity.current > 550);
    settle(close ? (ref.current?.offsetHeight || window.innerHeight) + 40 : 0);
  };
  return { onPointerDown, onPointerMove, onPointerUp: (event: PointerEvent<HTMLElement>) => end(event, false), onPointerCancel: (event: PointerEvent<HTMLElement>) => end(event, true) };
}
