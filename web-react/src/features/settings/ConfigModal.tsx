import { FormEvent, useEffect, useState } from 'react';
import { ApiError } from '../../api/client';
import { configApi } from '../../api/config';
import type { ModelConfig } from '../../api/types';
import { Modal } from '../../components/ui/Modal';

export function ConfigModal({
  open,
  config,
  onClose,
  onSaved,
}: {
  open: boolean;
  config: ModelConfig | null;
  onClose: () => void;
  onSaved: (config: ModelConfig) => void;
}) {
  const [baseUrl, setBaseUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [model, setModel] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setBaseUrl(config?.base_url || '');
    setModel(config?.model || '');
    setApiKey('');
    setError('');
  }, [open, config]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError('');
    setSaving(true);
    try {
      const payload: { base_url?: string; model?: string; api_key?: string } = {
        base_url: baseUrl.trim(),
        model: model.trim(),
      };
      if (apiKey.trim()) payload.api_key = apiKey.trim();
      const result = await configApi.update(payload);
      onSaved(result.config);
      onClose();
    } catch (caught) {
      const apiError = caught as ApiError;
      setError(apiError.data?.message || apiError.message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal open={open} title="模型设置" onClose={onClose}>
      <form className="skill-form" onSubmit={submit}>
        <div className="config-summary">
          <span>API URL</span>
          <span title={config?.base_url || ''}>{config?.base_url || '-'}</span>
          <span>API KEY</span>
          <span>{config?.api_key_masked || '<未设置>'}</span>
          <span>模型</span>
          <span>{config?.model || '-'}</span>
        </div>
        <label className="field-label">
          API URL
          <input className="skill-input" autoComplete="off" placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} />
        </label>
        <label className="field-label">
          API KEY
          <input className="skill-input" type="password" autoComplete="new-password" placeholder="留空则保留当前密钥" value={apiKey} onChange={(event) => setApiKey(event.target.value)} />
        </label>
        <label className="field-label">
          模型名称
          <input className="skill-input" autoComplete="off" placeholder="qwen-plus" value={model} onChange={(event) => setModel(event.target.value)} />
        </label>
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
