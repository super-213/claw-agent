import { useId, type ReactNode } from 'react';
import { X } from 'lucide-react';
import { useDialog } from './useDialog';
import { useSheetDrag } from './useSheetDrag';

export function BottomSheet({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const id = useId();
  const { ref, dismiss } = useDialog(true, onClose);
  const gestures = useSheetDrag(ref, dismiss);
  return <div className="pwa-sheet-backdrop" onClick={event => { if (event.target === event.currentTarget) dismiss(); }}>
    <section className="pwa-sheet" ref={ref} role="dialog" aria-modal="true" aria-labelledby={id} tabIndex={-1}>
      <div className="pwa-sheet-handle" aria-hidden="true" {...gestures}><span /></div>
      <header><h2 id={id}>{title}</h2><button type="button" onClick={dismiss} aria-label="关闭"><X size={20} /></button></header>
      <div className="pwa-sheet-content">{children}</div>
    </section>
  </div>;
}
