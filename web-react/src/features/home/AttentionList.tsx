import { expiryLabel, taskCaption, type Attention } from './attention';

export function AttentionList({
  entries,
  actor,
  today,
  busy,
  onOpen,
  onRun,
}: {
  entries: Attention[];
  actor: string | null;
  today: string;
  busy: string | null;
  onOpen: (path: string) => void;
  onRun: (entry: Attention) => Promise<void>;
}) {
  return (
    <>
      {entries.map((entry) => {
        const occ = entry.kind === 'task' ? entry.row.occurrence : null;
        const mineDone =
          actor && occ?.member_progress[actor]?.status === 'completed';
        const claim = entry.kind === 'task' && !occ?.assignee_ids.length;
        const actionable =
          entry.kind === 'item' ||
          claim ||
          (!mineDone && occ?.assignee_ids.includes(actor || ''));
        return (
          <article className="home-attention-row" key={entry.id}>
            <button
              type="button"
              className="home-row-title"
              onClick={() =>
                onOpen(
                  entry.kind === 'task'
                    ? `/home/tasks?task=${encodeURIComponent(entry.row.task.id)}`
                    : `/home/items?location=${entry.item.location}&item=${encodeURIComponent(entry.item.id)}`,
                )
              }
            >
              <strong>{entry.title}</strong>
              <small className={entry.priority === 0 ? 'home-risk' : ''}>
                {entry.kind === 'task'
                  ? taskCaption(entry.row, actor || null)
                  : expiryLabel(entry.item, today!)}
              </small>
            </button>
            {actionable ? (
              <button
                type="button"
                disabled={busy !== null}
                onClick={() => void onRun(entry)}
              >
                {busy === entry.id
                  ? '保存中…'
                  : entry.kind === 'item'
                    ? '用完'
                    : claim
                      ? '认领'
                      : occ!.assignee_ids.length > 1 &&
                          occ!.completion_mode === 'all'
                        ? '完成我的部分'
                        : entry.row.task.recurrence
                          ? '完成本周'
                          : '完成'}
              </button>
            ) : (
              <span className="home-muted">
                {mineDone ? '已完成我的部分' : '查看详情'}
              </span>
            )}
          </article>
        );
      })}
    </>
  );
}
