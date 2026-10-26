import type { FormEvent } from 'react';
import { Plus, ArrowRight, MessageCircle } from 'lucide-react';

export function AgentCommandBar({
  draft,
  onChange,
  onSubmit,
  onCreateTask,
  onCreateItem,
}: {
  draft: string;
  onChange: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
  onCreateTask: () => void;
  onCreateItem: () => void;
}) {
  return (
    <section className="home-command" aria-label="Agent 输入">
      <div className="home-command-title">
        <MessageCircle size={22} />
        <h2>家庭助手</h2>
      </div>
      <form onSubmit={onSubmit}>
        <input
          aria-label="和家庭 Agent 对话"
          placeholder="记一件事，或问问家里的安排…"
          value={draft}
          onChange={(e) => onChange(e.target.value)}
        />
        <button className="home-primary" type="submit" aria-label="发送" disabled={!draft.trim()}>
          <span>发送</span>
          <ArrowRight size={19} />
        </button>
      </form>
      <div className="home-command-actions">
        <button type="button" onClick={() => onCreateTask()}>
          <Plus size={17} />
          记录事项
        </button>
        <button type="button" onClick={() => onCreateItem()}>
          <Plus size={17} />
          添加物品
        </button>
      </div>
    </section>
  );
}
