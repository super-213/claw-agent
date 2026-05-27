import { FormEvent, useEffect, useState } from 'react';
import { adminApi } from '../../api/admin';
import { ApiError } from '../../api/client';
import { sessionsApi } from '../../api/sessions';
import type { ShareConfig, User } from '../../api/types';
import { Modal } from '../../components/ui/Modal';

const defaultSharing: ShareConfig = {
  scope: 'private',
  user_ids: [],
  permission: 'write',
};

export function ShareModal({
  open,
  sessionId,
  currentUserId,
  onClose,
  onSaved,
}: {
  open: boolean;
  sessionId: string | null;
  currentUserId?: string;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}) {
  const [users, setUsers] = useState<User[]>([]);
  const [sharing, setSharing] = useState<ShareConfig>(defaultSharing);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open || !sessionId) return;
    setError('');
    Promise.all([sessionsApi.share(sessionId), adminApi.shareableUsers()])
      .then(([shareData, userData]) => {
        setSharing(shareData.sharing || defaultSharing);
        setUsers(userData.users || []);
      })
      .catch((caught) => setError((caught as Error).message || '读取共享设置失败'));
  }, [open, sessionId]);

  const toggleUser = (userId: string) => {
    setSharing((current) => {
      const next = new Set(current.user_ids || []);
      if (next.has(userId)) next.delete(userId);
      else next.add(userId);
      return { ...current, user_ids: [...next] };
    });
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!sessionId) return;
    setSaving(true);
    setError('');
    try {
      await sessionsApi.updateShare(sessionId, sharing);
      await onSaved();
      onClose();
    } catch (caught) {
      const apiError = caught as ApiError;
      setError(apiError.data?.error || apiError.message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal open={open} title="共享设置" onClose={onClose}>
      <form className="skill-form" onSubmit={submit}>
        <label className="field-label">
          范围
          <select className="skill-input" value={sharing.scope} onChange={(event) => setSharing((current) => ({ ...current, scope: event.target.value }))}>
            <option value="private">私有</option>
            <option value="all">共享给所有人</option>
            <option value="selected">共享给指定用户</option>
          </select>
        </label>
        <label className="field-label">
          权限
          <select className="skill-input" value={sharing.permission} onChange={(event) => setSharing((current) => ({ ...current, permission: event.target.value }))}>
            <option value="write">可协作编辑</option>
            <option value="read">仅查看</option>
          </select>
        </label>
        <div className="field-label">
          指定用户
          <div className="share-user-list">
            {users
              .filter((user) => user.id !== currentUserId)
              .map((user) => (
                <label key={user.id} className="share-user-item">
                  <input type="checkbox" checked={(sharing.user_ids || []).includes(user.id)} onChange={() => toggleUser(user.id)} />
                  <span>
                    {user.display_name || user.username} · {user.username}
                  </span>
                </label>
              ))}
          </div>
        </div>
        <div className="skill-form-error">{error}</div>
        <div className="modal-actions">
          <button className="modal-secondary" type="button" onClick={onClose}>
            取消
          </button>
          <button className="modal-primary" type="submit" disabled={saving}>
            保存
          </button>
        </div>
      </form>
    </Modal>
  );
}
