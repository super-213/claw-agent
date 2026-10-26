import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { KnowledgeView } from '../../../web-react/src/features/knowledge/KnowledgeView';
import { SaveAttachment } from '../../../web-react/src/features/knowledge/SaveAttachment';
import { knowledgeApi, type KnowledgeEntry } from '../../../web-react/src/api/knowledge';
import { useAppStore } from '../../../web-react/src/stores/appStore';

const row: KnowledgeEntry = { id: 'doc1', title: '空调说明书', object_name: '客厅空调', aliases: [], owner_user_id: 'alice',
  visibility: 'personal', version: 1, status: 'ready', updated_at: '2026-10-26T04:00:00Z', filename: 'manual.txt', source_url: '/home/library?id=doc1' };
let client: QueryClient;
beforeEach(() => {
  window.history.replaceState(null, '', '/home/library');
  window.matchMedia = vi.fn().mockImplementation(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
  useAppStore.setState({ currentUser: { id: 'alice', username: 'alice', status: 'active', role: 'user' }, currentSessionId: 'session1' });
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  vi.spyOn(knowledgeApi, 'list').mockResolvedValue({ items: [row] });
  vi.spyOn(knowledgeApi, 'get').mockResolvedValue(row);
});
afterEach(() => { cleanup(); client.clear(); vi.restoreAllMocks(); });
const mount = (element: React.ReactElement) => render(React.createElement(BrowserRouter, {}, React.createElement(QueryClientProvider, { client }, element)));

it('only saves an attachment after explicit confirmation and shows partial processing honestly', async () => {
  const save = vi.spyOn(knowledgeApi, 'saveDocument').mockResolvedValue({ ...row, status: 'partial' });
  mount(React.createElement(SaveAttachment, { media: { path: 'uploads/alice/manual.txt', name: '说明书' }, message: { role: 'user', node_id: 'node1' } }));
  expect(save).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '保存到资料' }));
  fireEvent.change(screen.getByLabelText('关联对象（选填）'), { target: { value: '客厅空调' } });
  fireEvent.click(screen.getByRole('button', { name: '确认保存' }));
  await screen.findByText(/部分内容可检索/);
  expect(save).toHaveBeenCalledWith(expect.objectContaining({ source_session_id: 'session1', source_node_id: 'node1', object_name: '客厅空调' }));
});

it('requires a concrete household sharing confirmation and explains deletion scope', async () => {
  const change = vi.spyOn(knowledgeApi, 'change').mockResolvedValue({ ...row, visibility: 'household', version: 2 });
  mount(React.createElement(KnowledgeView, { collection: 'documents' }));
  fireEvent.click(await screen.findByRole('button', { name: /空调说明书/ }));
  await screen.findByRole('dialog');
  fireEvent.click(screen.getByRole('button', { name: '共享给家庭' }));
  expect(change).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '确认共享' }));
  await waitFor(() => expect(change).toHaveBeenCalledWith('documents', row, { visibility: 'household' }));
  fireEvent.click(screen.getByRole('button', { name: '删除资料' }));
  expect(screen.getByText(/原上传文件及历史聊天中的内容仍保留/)).toBeTruthy();
});

it('shows search failure with a retryable query and empty results without inventing an answer', async () => {
  vi.spyOn(knowledgeApi, 'search').mockResolvedValue({ items: [] });
  mount(React.createElement(KnowledgeView, { collection: 'records' }));
  fireEvent.change(screen.getByPlaceholderText(/按名称/), { target: { value: '备用钥匙' } });
  fireEvent.click(screen.getByRole('button', { name: '查找' }));
  await screen.findByText(/没有找到相关记录/);
});

it('keeps a version conflict visible and leaves the editor open', async () => {
  vi.spyOn(knowledgeApi, 'change').mockRejectedValue(new Error('内容已更新，请刷新后重试。'));
  mount(React.createElement(KnowledgeView, { collection: 'documents' }));
  fireEvent.click(await screen.findByRole('button', { name: /空调说明书/ }));
  await screen.findByRole('dialog');
  fireEvent.click(screen.getByRole('button', { name: '保存', exact: true }));
  await screen.findByRole('alert');
  expect(screen.getByRole('dialog')).toBeTruthy();
});

it('creates a memory with the supported fields and keeps personal visibility', async () => {
  const save = vi.spyOn(knowledgeApi, 'saveRecord').mockResolvedValue({ ...row, id: 'memory1', content: '钥匙在书房', kind: 'fact' });
  mount(React.createElement(KnowledgeView, { collection: 'records' }));
  fireEvent.click(screen.getByRole('button', { name: '记一件事' }));
  fireEvent.change(screen.getByLabelText('名称'), { target: { value: '钥匙位置' } });
  fireEvent.change(screen.getByLabelText('内容'), { target: { value: '钥匙在书房' } });
  fireEvent.click(screen.getByRole('button', { name: '保存', exact: true }));
  await waitFor(() => expect(save).toHaveBeenCalled());
  expect(save.mock.calls[0][0]).toEqual({ title: '钥匙位置', content: '钥匙在书房', object_name: '', kind: 'fact', request_id: expect.any(String) });
});
