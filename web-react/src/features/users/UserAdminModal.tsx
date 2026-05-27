import { FormEvent, useEffect, useState } from 'react';
import { adminApi } from '../../api/admin';
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

  const loadUsers = async () => {
    const data = await adminApi.users();
    setUsers(data.users || []);
  };

  useEffect(() => {
    if (!open) return;
    setError('');
    setForm(blank);
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
      if (form.id) {
        await adminApi.updateUser(form.id, payload);
        if (form.password) await adminApi.resetPassword(form.id, form.password);
      } else {
        await adminApi.createUser({ ...payload, password: form.password });
      }
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
            <button key={user.id} type="button" className={`user-row${form.id === user.id ? ' active' : ''}`} onClick={() => setForm(fromUser(user))}>
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
            <input className="skill-input" autoComplete="off" value={form.username} onChange={(event) => update({ username: event.target.value })} />
          </label>
          <label className="field-label">
            显示名称
            <input className="skill-input" autoComplete="off" value={form.displayName} onChange={(event) => update({ displayName: event.target.value })} />
          </label>
          <label className="field-label">
            密码
            <input
              className="skill-input"
              type="password"
              autoComplete="new-password"
              placeholder="编辑用户时留空则不修改"
              value={form.password}
              onChange={(event) => update({ password: event.target.value })}
            />
          </label>
          <div className="form-grid">
            <label className="field-label">
              角色
              <select className="skill-input" value={form.role} onChange={(event) => update({ role: event.target.value })}>
                <option value="user">普通用户</option>
                <option value="admin">管理员</option>
              </select>
            </label>
            <label className="field-label">
              状态
              <select className="skill-input" value={form.status} onChange={(event) => update({ status: event.target.value })}>
                <option value="active">启用</option>
                <option value="disabled">禁用</option>
              </select>
            </label>
          </div>
          <div className="skill-form-error">{error}</div>
          <div className="modal-actions">
            <button className="modal-secondary" type="button" onClick={() => setForm(blank)}>
              新建
            </button>
            <button className="modal-secondary danger-action" type="button" onClick={() => void deleteSelected()} disabled={!form.id}>
              删除
            </button>
            <button className="modal-secondary" type="button" onClick={onClose}>
              关闭
            </button>
            <button className="modal-primary" type="submit" disabled={saving}>
              {form.id ? '保存' : '创建'}
            </button>
          </div>
        </form>
      </div>
    </Modal>
  );
}
