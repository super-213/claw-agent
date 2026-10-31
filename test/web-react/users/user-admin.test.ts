import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { UserAdminModal } from '../../../web-react/src/features/users/UserAdminModal';
import { adminApi } from '../../../web-react/src/api/admin';
import { tasksApi } from '../../../web-react/src/api/tasks';

beforeEach(() => {
  vi.spyOn(adminApi, 'users').mockResolvedValue({ users: [] });
  vi.spyOn(adminApi, 'createUser').mockResolvedValue({ ok: true, user: { id: 'new-user', username: 'alice', status: 'active', role: 'user' } });
  vi.spyOn(tasksApi, 'members').mockResolvedValue({ current_member_id: null, members: [{ member_id: 'old', user_id: 'deleted', display_name: '原成员', aliases: [], status: 'disabled' }] });
  vi.spyOn(tasksApi, 'bindMember').mockResolvedValue({ member_id: 'new', user_id: 'new-user', display_name: 'alice', aliases: [], status: 'active' });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
async function mount() {
  render(React.createElement(UserAdminModal, { open: true, onClose: vi.fn() }));
  fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'alice' } });
  fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'secret123' } });
  await waitFor(() => expect(screen.getByRole('button', { name: '创建' })).toBeEnabled());
}
it('creates an account and a household member by default', async () => {
  await mount(); fireEvent.click(screen.getByRole('button', { name: '创建' }));
  await waitFor(() => expect(tasksApi.bindMember).toHaveBeenCalledWith('member_new-user', expect.objectContaining({ user_id: 'new-user', display_name: 'alice' })));
});
it('binds an existing identity without overwriting its name or aliases', async () => {
  await mount(); fireEvent.change(screen.getByRole('combobox', { name: /家庭成员/ }), { target: { value: 'old' } });
  fireEvent.click(screen.getByRole('button', { name: '创建' }));
  await waitFor(() => expect(tasksApi.bindMember).toHaveBeenCalledWith('old', { user_id: 'new-user', status: 'active' }));
});
it('retries a failed binding without creating a second account', async () => {
  vi.mocked(tasksApi.bindMember).mockRejectedValueOnce(new Error('network'));
  await mount(); fireEvent.click(screen.getByRole('button', { name: '创建' }));
  const retry = await screen.findByRole('button', { name: '重试绑定' });
  expect(screen.getByText(/账号已创建，但家庭成员绑定失败/)).toBeTruthy();
  fireEvent.click(retry);
  await waitFor(() => expect(tasksApi.bindMember).toHaveBeenCalledTimes(2));
  expect(adminApi.createUser).toHaveBeenCalledTimes(1);
});
it('can create only a login account', async () => {
  await mount(); fireEvent.change(screen.getByRole('combobox', { name: /家庭成员/ }), { target: { value: 'none' } });
  fireEvent.click(screen.getByRole('button', { name: '创建' }));
  await waitFor(() => expect(adminApi.createUser).toHaveBeenCalledTimes(1));
  expect(tasksApi.bindMember).not.toHaveBeenCalled();
});
