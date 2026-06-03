import React, { act, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Composer } from '../../../web-react/src/features/chat/Composer';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const setPointerMode = (isCoarsePointer: boolean) => {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: isCoarsePointer,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
};

const renderComposer = async (onSend = vi.fn()) => {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  const Harness = () => {
    const [draft, setDraft] = useState('hello');
    return React.createElement(Composer, {
      disabled: false,
      draft,
      onDraftChange: setDraft,
      onSend,
      onUploadFiles: async () => [],
    });
  };

  await act(async () => {
    root.render(React.createElement(Harness));
  });

  return {
    container,
    onSend,
    input: container.querySelector('textarea') as HTMLTextAreaElement,
    unmount: () => {
      act(() => root.unmount());
      container.remove();
    },
  };
};

const pressEnter = (input: HTMLTextAreaElement) => {
  act(() => {
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
  });
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe('Composer keyboard behavior', () => {
  it('sends with Enter on desktop-style pointers', async () => {
    setPointerMode(false);
    const view = await renderComposer();

    pressEnter(view.input);

    expect(view.onSend).toHaveBeenCalledWith('hello', []);
    view.unmount();
  });

  it('keeps Enter as text input on touch pointers', async () => {
    setPointerMode(true);
    const view = await renderComposer();

    expect(view.container.textContent).toContain('点击发送按钮提交');
    pressEnter(view.input);

    expect(view.onSend).not.toHaveBeenCalled();
    view.unmount();
  });
});
