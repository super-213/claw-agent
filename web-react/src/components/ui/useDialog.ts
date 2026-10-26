import { useCallback, useEffect, useRef } from 'react';

// A single history entry belongs to each open layer. Back dismisses that layer
// without losing the underlying view, filters, scroll position or draft.
export function useDialog(open: boolean, onClose: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  const id = useRef(`dialog-${Math.random().toString(36).slice(2)}`);
  const active = useRef(false);
  const dismiss = useCallback(() => {
    if (window.history.state?.homeDialog === id.current) window.history.back();
    else closeRef.current();
  }, []);

  useEffect(() => {
    if (!open || !ref.current) return;
    active.current = true;
    const dialogId = id.current;
    const node = ref.current;
    const trigger = document.activeElement as HTMLElement | null;
    const scrollY = window.scrollY;
    const oldOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    if (window.history.state?.homeDialog !== dialogId)
      window.history.pushState(
        { ...window.history.state, homeDialog: dialogId },
        '',
        window.location.href,
      );
    const blocked: { node: HTMLElement; inert: boolean }[] = [];
    let parent: HTMLElement | null = node;
    while (parent && parent !== document.body) {
      for (const sibling of Array.from(parent.parentElement?.children || [])) {
        if (sibling !== parent && sibling instanceof HTMLElement) {
          blocked.push({ node: sibling, inert: sibling.inert });
          sibling.inert = true;
        }
      }
      parent = parent.parentElement;
    }
    const focusable = () =>
      Array.from(
        node.querySelectorAll<HTMLElement>(
          'button, a[href], input, select, textarea, [tabindex="0"]',
        ),
      ).filter(
        (el) =>
          !el.hasAttribute('disabled') &&
          !el.closest('[hidden], [inert]') &&
          el.getClientRects().length > 0,
      );
    const timer = window.setTimeout(() => (focusable()[0] || node).focus(), 0);
    const pop = () => {
      if (window.history.state?.homeDialog !== dialogId) closeRef.current();
    };
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        dismiss();
      }
      if (event.key === 'Tab') {
        const elements = focusable();
        const first = elements[0] || node;
        const last = elements[elements.length - 1] || node;
        if (
          event.shiftKey &&
          (document.activeElement === first ||
            !node.contains(document.activeElement))
        ) {
          event.preventDefault();
          last.focus();
        } else if (
          !event.shiftKey &&
          (document.activeElement === last ||
            !node.contains(document.activeElement))
        ) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener('popstate', pop);
    node.addEventListener('keydown', key);
    return () => {
      active.current = false;
      window.clearTimeout(timer);
      window.removeEventListener('popstate', pop);
      node.removeEventListener('keydown', key);
      blocked.forEach((entry) => {
        entry.node.inert = entry.inert;
      });
      document.body.style.overflow = oldOverflow;
      if (trigger?.isConnected) trigger.focus({ preventScroll: true });
      window.scrollTo(0, scrollY);
      // Successful saves can close a layer without a user pressing Back.
      window.setTimeout(() => {
        if (!active.current && window.history.state?.homeDialog === dialogId)
          window.history.back();
      }, 0);
    };
  }, [open, dismiss]);
  return { ref, dismiss };
}
