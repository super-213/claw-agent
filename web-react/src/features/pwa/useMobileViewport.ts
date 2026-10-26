import { useEffect } from 'react';

export function useMobileViewport() {
  useEffect(() => {
    const viewport = window.visualViewport;
    if (!viewport) return;
    const root = document.documentElement;
    let frame = 0;
    const update = () => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        const mobile = window.matchMedia('(max-width: 860px)').matches;
        // Pinch zoom belongs to the user; don't reflow their enlarged page.
        if (!mobile || Math.abs(viewport.scale - 1) > 0.05) return;
        root.style.setProperty('--app-height', `${viewport.height}px`);
        root.style.setProperty('--viewport-top', `${viewport.offsetTop}px`);
        const focused = document.activeElement?.matches('input, textarea, [contenteditable=true]');
        root.classList.toggle('keyboard-open', Boolean(focused && window.innerHeight - viewport.height > 120));
      });
    };
    viewport.addEventListener('resize', update);
    viewport.addEventListener('scroll', update);
    window.addEventListener('resize', update);
    document.addEventListener('focusin', update);
    document.addEventListener('focusout', update);
    update();
    return () => {
      window.cancelAnimationFrame(frame);
      viewport.removeEventListener('resize', update);
      viewport.removeEventListener('scroll', update);
      window.removeEventListener('resize', update);
      document.removeEventListener('focusin', update);
      document.removeEventListener('focusout', update);
      root.style.removeProperty('--app-height');
      root.style.removeProperty('--viewport-top');
      root.classList.remove('keyboard-open');
    };
  }, []);
}
