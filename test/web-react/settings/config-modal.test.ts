import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { configApi } from '../../../web-react/src/api/config';
import { ConfigModal } from '../../../web-react/src/features/settings/ConfigModal';

vi.mock('../../../web-react/src/api/config', () => ({
  configApi: { models: vi.fn(), update: vi.fn() },
}));

const config = { base_url: 'https://saved.example/v1', model: 'qwen-plus', vision_model: '' };
const list = [
  { id: 'qwen-plus', owned_by: 'vendor' },
  { id: 'qwen-max', owned_by: 'vendor' },
  { id: 'qwen3-vl-plus', owned_by: 'vendor' },
];

const show = () => {
  const onSaved = vi.fn();
  const onClose = vi.fn();
  render(React.createElement(ConfigModal, { open: true, config, onSaved, onClose }));
  return { onSaved, onClose };
};

beforeEach(() => {
  vi.mocked(configApi.models).mockResolvedValue({ models: list });
  vi.mocked(configApi.update).mockResolvedValue({ ok: true, config: { ...config, model: 'qwen-max', vision_model: 'qwen3-vl-plus' } });
});

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe('administrator model selection', () => {
  it('fetches API models and saves selected text and vision models', async () => {
    const { onSaved, onClose } = show();
    await waitFor(() => expect(screen.getByRole('combobox', { name: '文本模型' })).toBeEnabled());
    expect(configApi.models).toHaveBeenCalledWith({ base_url: config.base_url }, expect.any(AbortSignal));
    fireEvent.change(screen.getByRole('combobox', { name: '文本模型' }), { target: { value: 'qwen-max' } });
    fireEvent.change(screen.getByRole('combobox', { name: '视觉模型' }), { target: { value: 'qwen3-vl-plus' } });
    fireEvent.click(screen.getByRole('button', { name: '保存' }));
    await waitFor(() => expect(configApi.update).toHaveBeenCalledWith(expect.objectContaining({ model: 'qwen-max', vision_model: 'qwen3-vl-plus' })));
    expect(onSaved).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it('previews changed credentials without saving and resets previous selections', async () => {
    show();
    await waitFor(() => expect(screen.getByRole('combobox', { name: '文本模型' })).toBeEnabled());
    fireEvent.change(screen.getByRole('combobox', { name: '文本模型' }), { target: { value: 'qwen-max' } });
    fireEvent.change(screen.getByLabelText('API URL'), { target: { value: 'https://new.example/v1' } });
    fireEvent.change(screen.getByLabelText('API KEY'), { target: { value: 'new-key' } });
    expect(screen.getByRole('combobox', { name: '文本模型' })).toBeDisabled();
    expect(screen.getByRole('combobox', { name: '文本模型' })).toHaveValue('qwen-plus');
    fireEvent.click(screen.getByRole('button', { name: '刷新模型列表' }));
    await waitFor(() => expect(configApi.models).toHaveBeenLastCalledWith({ base_url: 'https://new.example/v1', api_key: 'new-key' }, expect.any(AbortSignal)));
    expect(configApi.update).not.toHaveBeenCalled();
  });

  it('keeps the current model and automatic vision option on provider failure', async () => {
    vi.mocked(configApi.models).mockRejectedValue(new Error('模型服务鉴权失败'));
    show();
    expect(await screen.findByRole('alert')).toHaveTextContent('鉴权失败');
    expect(screen.getByRole('combobox', { name: '文本模型' })).toHaveValue('qwen-plus');
    expect(screen.getByRole('combobox', { name: '文本模型' })).toBeDisabled();
    expect(screen.getByRole('combobox', { name: '视觉模型' })).toHaveValue('');
    expect(configApi.update).not.toHaveBeenCalled();
  });

  it('allows searching a large list without losing the selected model', async () => {
    show();
    const search = await screen.findByRole('searchbox', { name: '搜索可用模型' });
    fireEvent.change(search, { target: { value: 'vl' } });
    const select = screen.getByRole('combobox', { name: '文本模型' }) as HTMLSelectElement;
    expect(Array.from(select.options).map((option) => option.value)).toEqual(['qwen-plus', 'qwen3-vl-plus']);
    expect(select).toHaveValue('qwen-plus');
  });

  it('preserves saved models missing from the provider list and handles empty lists', async () => {
    vi.mocked(configApi.models).mockResolvedValue({ models: [] });
    show();
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('0 个模型'));
    const select = screen.getByRole('combobox', { name: '文本模型' });
    expect(select).toHaveValue('qwen-plus');
    expect(select).toHaveTextContent('当前配置，接口未列出');
    expect(select).toBeDisabled();
  });

  it('ignores an old response after credentials change', async () => {
    let resolveOld!: (value: { models: typeof list }) => void;
    vi.mocked(configApi.models).mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }));
    show();
    fireEvent.change(screen.getByLabelText('API URL'), { target: { value: 'https://new.example/v1' } });
    vi.mocked(configApi.models).mockResolvedValue({ models: [{ id: 'new-provider-model', owned_by: 'vendor' }] });
    fireEvent.click(screen.getByRole('button', { name: '刷新模型列表' }));
    await waitFor(() => expect(screen.getByRole('combobox', { name: '文本模型' })).toBeEnabled());
    resolveOld({ models: list });
    await waitFor(() => {
      const select = screen.getByRole('combobox', { name: '文本模型' }) as HTMLSelectElement;
      expect(Array.from(select.options).map((option) => option.value)).toEqual(['qwen-plus', 'new-provider-model']);
    });
  });
});
