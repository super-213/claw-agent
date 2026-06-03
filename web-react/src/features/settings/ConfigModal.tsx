import { FormEvent, useEffect, useState } from 'react';
import { ApiError } from '../../api/client';
import { configApi, type ConfigUpdatePayload } from '../../api/config';
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
  const [haBaseUrl, setHaBaseUrl] = useState('');
  const [haToken, setHaToken] = useState('');
  const [haAllowedEntities, setHaAllowedEntities] = useState('');
  const [haRequestTimeout, setHaRequestTimeout] = useState('10');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setBaseUrl(config?.base_url || '');
    setModel(config?.model || '');
    setApiKey('');
    setHaBaseUrl(config?.home_assistant?.base_url || '');
    setHaToken('');
    setHaAllowedEntities(config?.home_assistant?.allowed_entities || '');
    setHaRequestTimeout(String(config?.home_assistant?.request_timeout || 10));
    setError('');
  }, [open, config]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError('');
    setSaving(true);
    try {
      const payload: ConfigUpdatePayload = {
        base_url: baseUrl.trim(),
        model: model.trim(),
      };
      if (apiKey.trim()) payload.api_key = apiKey.trim();
      const timeout = Number.parseInt(haRequestTimeout, 10);
      const result = await configApi.update({
        ...payload,
        home_assistant: {
          base_url: haBaseUrl.trim(),
          allowed_entities: haAllowedEntities.trim(),
          request_timeout: Number.isFinite(timeout) ? timeout : 10,
          ...(haToken.trim() ? { token: haToken.trim() } : {}),
        },
      });
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
    <Modal open={open} title="模型与 Home Assistant 设置" onClose={onClose}>
      <form className="skill-form" onSubmit={submit}>
        <div className="config-section-title">大模型</div>
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
        <div className="config-section-title">Home Assistant</div>
        <div className="config-summary">
          <span>HA URL</span>
          <span title={config?.home_assistant?.base_url || ''}>{config?.home_assistant?.base_url || '-'}</span>
          <span>Token</span>
          <span>{config?.home_assistant?.token_masked || '<未设置>'}</span>
          <span>白名单</span>
          <span>{config?.home_assistant?.allowed_entity_count ?? 0} 个 entity</span>
          <span>状态</span>
          <span>{config?.home_assistant?.configured ? '已配置' : '未配置'}</span>
          {config?.home_assistant?.config_error ? (
            <>
              <span>配置错误</span>
              <span>{config.home_assistant.config_error}</span>
            </>
          ) : null}
        </div>
        <label className="field-label">
          Home Assistant URL
          <input className="skill-input" autoComplete="off" placeholder="http://192.168.1.20:8123" value={haBaseUrl} onChange={(event) => setHaBaseUrl(event.target.value)} />
        </label>
        <label className="field-label">
          Home Assistant Token
          <input className="skill-input" type="password" autoComplete="new-password" placeholder="留空则保留当前 Token" value={haToken} onChange={(event) => setHaToken(event.target.value)} />
        </label>
        <label className="field-label">
          设备白名单
          <textarea
            className="skill-textarea config-entities-textarea"
            placeholder={'switch.desk_lamp|书桌插座\nlight.living_room|客厅灯|客厅主灯'}
            value={haAllowedEntities}
            onChange={(event) => setHaAllowedEntities(event.target.value)}
          />
        </label>
        <label className="field-label">
          请求超时秒数
          <input className="skill-input" type="number" min="1" max="120" value={haRequestTimeout} onChange={(event) => setHaRequestTimeout(event.target.value)} />
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
