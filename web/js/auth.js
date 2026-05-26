import { adminApi, authApi } from './api.js';
import { els } from './dom.js';
import { state } from './state.js';
import { escapeHtml } from './utils.js';

const isAdmin = () => state.currentUser?.role === 'admin';

const setUserForm = (user = null) => {
  els.userIdInput.value = user?.id || '';
  els.userUsernameInput.value = user?.username || '';
  els.userDisplayNameInput.value = user?.display_name || '';
  els.userPasswordInput.value = '';
  els.userRoleInput.value = user?.role || 'user';
  els.userStatusInput.value = user?.status === 'disabled' ? 'disabled' : 'active';
  els.userFormError.textContent = '';
  els.userSaveBtn.textContent = user ? '保存' : '创建';
};

const renderUsers = () => {
  els.userList.innerHTML = '';
  state.users.forEach((user) => {
    const row = document.createElement('button');
    row.type = 'button';
    row.className = 'user-row' + (els.userIdInput.value === user.id ? ' active' : '');
    row.innerHTML = `
      <strong>${escapeHtml(user.display_name || user.username)}</strong>
      <span>${escapeHtml(user.username)} · ${escapeHtml(user.role)} · ${escapeHtml(user.status)}</span>
    `;
    row.addEventListener('click', () => {
      setUserForm(user);
      renderUsers();
    });
    els.userList.appendChild(row);
  });
};

export const requireLogin = async () => {
  try {
    const data = await authApi.me();
    state.currentUser = data.user;
  } catch {
    window.location.href = '/login';
    return false;
  }
  if (els.userSummary) {
    els.userSummary.innerHTML = `
      <span>当前用户</span>
      <strong>${escapeHtml(state.currentUser.display_name || state.currentUser.username)} · ${escapeHtml(state.currentUser.role)}</strong>
    `;
  }
  if (els.userAdminBtn) {
    els.userAdminBtn.hidden = !isAdmin();
  }
  if (els.configBtn) {
    els.configBtn.hidden = !isAdmin();
  }
  return true;
};

export const logout = async () => {
  await authApi.logout().catch(() => {});
  window.location.href = '/login';
};

export const loadUsers = async () => {
  if (!isAdmin()) return [];
  const data = await adminApi.users();
  state.users = data.users || [];
  return state.users;
};

export const openUserAdminModal = async () => {
  if (!isAdmin()) return;
  els.userAdminModal.classList.add('open');
  els.userAdminModal.setAttribute('aria-hidden', 'false');
  await loadUsers();
  setUserForm(null);
  renderUsers();
};

export const closeUserAdminModal = () => {
  els.userAdminModal.classList.remove('open');
  els.userAdminModal.setAttribute('aria-hidden', 'true');
};

export const resetUserForm = () => {
  setUserForm(null);
  renderUsers();
};

export const submitUserForm = async (event) => {
  event.preventDefault();
  els.userFormError.textContent = '';
  const userId = els.userIdInput.value;
  const payload = {
    username: els.userUsernameInput.value.trim(),
    display_name: els.userDisplayNameInput.value.trim(),
    role: els.userRoleInput.value,
    status: els.userStatusInput.value,
  };
  try {
    if (userId) {
      await adminApi.updateUser(userId, payload);
      if (els.userPasswordInput.value) {
        await adminApi.resetPassword(userId, els.userPasswordInput.value);
      }
    } else {
      await adminApi.createUser({
        ...payload,
        password: els.userPasswordInput.value,
      });
    }
    await loadUsers();
    setUserForm(null);
    renderUsers();
  } catch (error) {
    const code = error.data?.error || '';
    els.userFormError.textContent = {
      username_exists: '用户名已存在',
      invalid_username: '用户名需要 2-40 位且不能包含空格',
      weak_password: '创建用户或重置密码时密码至少需要 6 位',
      invalid_role: '角色无效',
      invalid_status: '状态无效',
      last_admin: '不能删除或禁用最后一个管理员',
    }[code] || error.message || '保存失败';
  }
};

export const deleteSelectedUser = async () => {
  const userId = els.userIdInput.value;
  if (!userId) return;
  const user = state.users.find((item) => item.id === userId);
  if (!user) return;
  if (!confirm(`删除用户「${user.username}」？`)) return;
  try {
    await adminApi.deleteUser(userId);
    await loadUsers();
    setUserForm(null);
    renderUsers();
  } catch (error) {
    els.userFormError.textContent = error.data?.error || error.message || '删除失败';
  }
};
