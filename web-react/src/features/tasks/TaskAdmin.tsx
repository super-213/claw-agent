import { useState, type FormEvent } from 'react';
import { adminApi } from '../../api/admin';
import { tasksApi, type FamilyMember } from '../../api/tasks';
import type { User } from '../../api/types';

export function TaskAdmin() {
  const [members, setMembers] = useState<FamilyMember[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [accounts, setAccounts] = useState<User[]>([]);
  const [bindAccount, setBindAccount] = useState('');
  const [bindName, setBindName] = useState('');
  const [bindAliases, setBindAliases] = useState('');
  const [memberEdit, setMemberEdit] = useState('');
  const [speakerAliases, setSpeakerAliases] = useState('{}');
  const [review, setReview] = useState<Record<
    string,
    { reasons: string[]; source: { title?: string } }
  > | null>(null);
  const run = async (action: () => Promise<unknown>) => {
    setSaving(true);
    setError('');
    try {
      await action();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };
  const bind = async (event: FormEvent) => {
    event.preventDefault();
    await run(async () => {
      await tasksApi.bindMember(memberEdit || `member_${bindAccount}`, {
        user_id: bindAccount,
        display_name: bindName,
        aliases: bindAliases
          .split(/[、,]/)
          .map((s) => s.trim())
          .filter(Boolean),
        speaker_aliases: JSON.parse(speakerAliases),
      });
      setMembers((await tasksApi.members()).members);
    });
  };
  return (
    <section className="task-admin-page">
      {error && <p role="alert">{error}</p>}{' '}
      <details className="task-admin">
        <summary
          onClick={() => {
            void run(async () => {
              setAccounts((await adminApi.users()).users);
              setMembers((await tasksApi.members()).members);
            });
          }}
        >
          家庭成员绑定与迁移核对（管理员）
        </summary>
        <p>
          只有显式绑定的有效账号才能使用家庭事项，不会自动授权全部账号。技术管理员仍可管理会话。
        </p>
        <form onSubmit={(e) => void bind(e)}>
          <label>
            现有成员
            <select
              value={memberEdit}
              onChange={(e) => {
                setMemberEdit(e.target.value);
                const m = members.find((v) => v.member_id === e.target.value);
                if (m) {
                  setBindAccount(m.user_id);
                  setBindName(m.display_name);
                  setBindAliases(m.aliases.join('、'));
                }
              }}
            >
              <option value="">新增绑定</option>
              {members.map((m) => (
                <option key={m.member_id} value={m.member_id}>
                  {m.display_name}
                </option>
              ))}
            </select>
          </label>
          <label>
            账号
            <select
              required
              value={bindAccount}
              onChange={(e) => {
                setBindAccount(e.target.value);
                const account = accounts.find((a) => a.id === e.target.value);
                if (account)
                  setBindName(account.display_name || account.username);
              }}
            >
              <option value="">选择有效账号</option>
              {accounts
                .filter((a) => a.status === 'active')
                .map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.display_name || a.username}
                  </option>
                ))}
            </select>
          </label>
          <label>
            成员姓名
            <input
              required
              value={bindName}
              onChange={(e) => setBindName(e.target.value)}
            />
          </label>
          <label>
            通用称呼
            <input
              value={bindAliases}
              placeholder="以顿号分隔"
              onChange={(e) => setBindAliases(e.target.value)}
            />
          </label>
          <label>
            该成员的称呼映射（称呼 → 成员 ID）
            <input
              value={speakerAliases}
              onChange={(e) => setSpeakerAliases(e.target.value)}
            />
          </label>
          <button disabled={saving} type="submit">
            保存绑定
          </button>
        </form>
        <button
          type="button"
          onClick={() =>
            void tasksApi.migrationReview().then((r) => setReview(r.records))
          }
        >
          查看迁移待核对记录
        </button>
        {review && (
          <ul>
            {Object.entries(review).map(([id, record]) => (
              <li key={id}>
                {record.source.title || id}：{record.reasons.join('、')}
              </li>
            ))}
          </ul>
        )}
      </details>
    </section>
  );
}
