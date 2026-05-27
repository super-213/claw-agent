import { Send } from 'lucide-react';
import { KeyboardEvent, useEffect, useRef } from 'react';

export function Composer({
  disabled,
  draft,
  onDraftChange,
  onSend,
}: {
  disabled: boolean;
  draft: string;
  onDraftChange: (value: string) => void;
  onSend: (text: string) => void | Promise<void>;
}) {
  const ref = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
  }, [draft]);

  const send = async () => {
    const trimmed = draft.trim();
    if (!trimmed || disabled) return;
    onDraftChange('');
    await onSend(trimmed);
  };

  const keyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void send();
    }
  };

  return (
    <div className="composer-area">
      <div className="composer">
        <textarea
          ref={ref}
          placeholder="输入指令或问题..."
          rows={1}
          value={draft}
          disabled={disabled}
          onKeyDown={keyDown}
          onChange={(event) => onDraftChange(event.target.value)}
        />
        <button className="send-btn" title="发送 (Enter)" type="button" disabled={disabled || !draft.trim()} onClick={() => void send()}>
          <Send size={20} />
        </button>
      </div>
      <div className="composer-hint">Enter 发送 · Shift+Enter 换行</div>
    </div>
  );
}
