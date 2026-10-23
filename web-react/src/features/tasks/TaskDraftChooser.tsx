import { taskCommands, type TaskCommand } from '../../api/tasks';

export interface TaskDraft { sessionId: string; items: Array<{ title: string }>; message: string }

export function TaskDraftChooser({ draft, onChoose, onDismiss }: {
  draft: TaskDraft; onChoose: (command: TaskCommand, body: string) => void; onDismiss: () => void;
}) {
  return <section className="task-draft-chooser" aria-label="待补充事项草稿">
    <strong>草稿尚未保存为事项</strong><p>{draft.message}</p>
    <ul>{draft.items.map((item, i) => <li key={i}>{item.title}</li>)}</ul>
    <div className="row-actions">{taskCommands.map(command => <button type="button" key={command}
      onClick={() => onChoose(command, draft.items.map(item => item.title).join('、'))}>/ {command}</button>)}
      <button type="button" onClick={onDismiss}>收起草稿</button></div>
  </section>;
}
