import { FormEvent, useEffect, useState } from 'react';
import { adminApi } from '../../api/admin';
import { tasksApi, type FamilyMember } from '../../api/tasks';
import { ApiError } from '../../api/client';
import type { User } from '../../api/types';
import { Modal } from '../../components/ui/Modal';

const userErrorText: Record<string, string> = {
  username_exists: '用户名已存在',
  invalid_username: '用户名需要 2-40 位且不能包含空格',
  weak_password: '创建用户或重置密码时密码至少需要 6 位',
  invalid_role: '角色无效',
  invalid_status: '状态无效',
  last_admin: '不能删除或禁用最后一个管理员',
};

interface FormState {
  id: string;
  username: string;
  displayName: string;
  password: string;
  role: string;
  status: string;
}

const blank: FormState = {
  id: '',
  username: '',
  displayName: '',
  password: '',
  role: 'user',
  status: 'active',
};

const fromUser = (user: User): FormState => ({
  id: user.id,
  username: user.username,
  displayName: user.display_name || '',
  password: '',
  role: user.role || 'user',
  status: user.status === 'disabled' ? 'disabled' : 'active',
});

export function UserAdminModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [users, setUsers] = useState<User[]>([]);
  const [form, setForm] = useState<FormState>(blank);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [members, setMembers] = useState<FamilyMember[]>([]);
  const [binding, setBinding] = useState('new');
  const [pendingBinding, setPendingBinding] = useState(false);
  const [membersReady, setMembersReady] = useState(false);

  const loadUsers = async () => {
    const data = await adminApi.users();
    setUsers(data.users || []);
  };

  useEffect(() => {
    if (!open) return;
    setError('');
    setForm(blank);
    setBinding('new');
    setPendingBinding(false);
    setMembersReady(false);
    void tasksApi.members().then(data => { setMembers(data.members); setMembersReady(true); })
      .catch(() => setError('读取家庭成员失败，请关闭后重试；仍可选择仅创建账号。'));
    void loadUsers().catch((caught) => setError((caught as Error).message || '读取用户失败'));
  }, [open]);

  const update = (patch: Partial<FormState>) => setForm((current) => ({ ...current, ...patch }));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError('');
    setSaving(true);
    try {
      const payload = {
        username: form.username.trim(),
        display_name: form.displayName.trim(),
        role: form.role,
        status: form.status,
      };
      let userId = form.id;
      if (form.id && !pendingBinding) {
        await adminApi.updateUser(form.id, payload);
        if (form.password) await adminApi.resetPassword(form.id, form.password);
      } else {
        if (!userId) {
          const result = await adminApi.createUser({ ...payload, password: form.password });
          userId = result.user.id;
          // Keep the created account on a binding failure so retry never creates it twice.
          setForm({ ...form, id: userId, password: '' });
          setPendingBinding(binding !== 'none');
        }
        if (binding !== 'none') {
          try {
            await tasksApi.bindMember(binding === 'new' ? `member_${userId}` : binding, {
              user_id: userId,
              ...(binding === 'new' ? { display_name: payload.display_name || payload.username, aliases: [], speaker_aliases: {} } : {}),
              status: 'active',
            });
          } catch {
            setError('账号已创建，但家庭成员绑定失败。请点击“重试绑定”，或到家庭成员管理中完成绑定。');
            return;
          }
        }
      }
      setPendingBinding(false);
      setBinding('new');
      if (membersReady) setMembers((await tasksApi.members()).members);
      await loadUsers();
      setForm(blank);
    } catch (caught) {
      const apiError = caught as ApiError;
      const code = apiError.data?.error || '';
      setError(userErrorText[code] || apiError.message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const deleteSelected = async () => {
    if (!form.id) return;
    const user = users.find((item) => item.id === form.id);
    if (!user || !confirm(`删除用户「${user.username}」？`)) return;
    try {
      await adminApi.deleteUser(form.id);
      await loadUsers();
      setForm(blank);
    } catch (caught) {
      const apiError = caught as ApiError;
      setError(apiError.data?.error || apiError.message || '删除失败');
    }
  };

  return (
    <Modal open={open} title="用户管理" className="user-admin-modal" onClose={onClose}>
      <div className="admin-user-layout">
        <div className="user-list">
          {users.map((user) => (
            <button key={user.id} type="button" className={`user-row${form.id === user.id ? ' active' : ''}`} disabled={saving || pendingBinding} onClick={() => { setForm(fromUser(user)); setError(''); }}>
              <strong>{user.display_name || user.username}</strong>
              <span>
                {user.username} · {user.role} · {user.status}
              </span>
            </button>
          ))}
        </div>
        <form className="skill-form user-form" onSubmit={submit}>
          <label className="field-label">
            用户名
            <input className="skill-input" autoComplete="off" disabled={pendingBinding || saving} value={form.username} onChange={(event) => update({ username: event.target.value })} />
          </label>
          <label className="field-label">
            显示名称
            <input className="skill-input" autoComplete="off" disabled={pendingBinding || saving} value={form.displayName} onChange={(event) => update({ displayName: event.target.value })} />
          </label>
          <label className="field-label">
            密码
            <input
              className="skill-input"
              type="password"
              autoComplete="new-password"
              disabled={pendingBinding || saving}
              placeholder="编辑用户时留空则不修改"
              value={form.password}
              onChange={(event) => update({ password: event.target.value })}
            />
          </label>
          <div className="form-grid">
            <label className="field-label">
              角色
              <select disabled={pendingBinding || saving} className="skill-input" value={form.role} onChange={(event) => update({ role: event.target.value })}>
                <option value="user">普通用户</option>
                <option value="admin">管理员</option>
              </select>
            </label>
            <label className="field-label">
              状态
              <select disabled={pendingBinding || saving} className="skill-input" value={form.status} onChange={(event) => update({ status: event.target.value })}>
                <option value="active">启用</option>
                <option value="disabled">禁用</option>
              </select>
            </label>
          </div>
          {(!form.id || pendingBinding) && <label className="field-label">
            家庭成员
            <select className="skill-input" value={binding} disabled={saving} onChange={event => setBinding(event.target.value)}>
              <option value="new">同时添加为家庭成员</option>
              {members.filter(member => !users.some(user => user.id === member.user_id && user.status === 'active'))
                .map(member => <option key={member.member_id} value={member.member_id}>绑定已有成员：{member.display_name}</option>)}
              <option value="none">仅创建账号，暂不绑定</option>
            </select>
            <small>已有成员绑定会保留历史事项；已绑定有效账号的成员请到家庭成员管理中调整。仅创建账号将无法读取家庭数据。</small>
          </label>}
          {(!form.id || pendingBinding) && form.status === 'disabled' && binding !== 'none' && <p role="status">绑定家庭成员需要启用账号，请将状态设为启用。</p>}
          <div className="skill-form-error" role="alert">{error}</div>
          <div className="modal-actions">
            <button className="modal-secondary" type="button" disabled={saving} onClick={() => { setForm(blank); setPendingBinding(false); setBinding('new'); setError(''); }}>
              新建
            </button>
            <button className="modal-secondary danger-action" type="button" onClick={() => void deleteSelected()} disabled={!form.id || saving || pendingBinding}>
              删除
            </button>
            <button className="modal-secondary" type="button" onClick={onClose}>
              关闭
            </button>
            <button className="modal-primary" type="submit" disabled={saving || ((!form.id || pendingBinding) && binding !== 'none' && (!membersReady || form.status !== 'active'))}>
              {pendingBinding ? '重试绑定' : form.id ? '保存' : '创建'}
            </button>
          </div>
        </form>
      </div>
    </Modal>
  );
}
