import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '../../api/client';
import { configApi, type AvailableModel, type ConfigUpdatePayload } from '../../api/config';
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
  const [visionModel, setVisionModel] = useState('');
  const [haBaseUrl, setHaBaseUrl] = useState('');
  const [haToken, setHaToken] = useState('');
  const [haAllowedEntities, setHaAllowedEntities] = useState('');
  const [haRequestTimeout, setHaRequestTimeout] = useState('10');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [models, setModels] = useState<AvailableModel[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsReady, setModelsReady] = useState(false);
  const [modelsError, setModelsError] = useState('');
  const [modelSearch, setModelSearch] = useState('');
  const modelRequest = useRef<AbortController | null>(null);

  const loadModels = useCallback(async (url: string, key: string) => {
    modelRequest.current?.abort();
    const controller = new AbortController();
    modelRequest.current = controller;
    setModelsLoading(true);
    setModelsReady(false);
    setModelsError('');
    setModels([]);
    try {
      const result = await configApi.models({ base_url: url.trim(), ...(key.trim() ? { api_key: key.trim() } : {}) }, controller.signal);
      if (controller.signal.aborted) return;
      setModels(result.models);
      setModelsReady(true);
    } catch (caught) {
      if (controller.signal.aborted) return;
      const apiError = caught as ApiError;
      setModelsError(apiError.data?.message || apiError.message || '获取模型列表失败');
    } finally {
      if (!controller.signal.aborted) setModelsLoading(false);
    }
  }, []);

  const invalidateModels = () => {
    modelRequest.current?.abort();
    setModels([]);
    setModelsLoading(false);
    setModelsReady(false);
    setModelsError('API URL 或密钥已更改，请重新获取模型列表');
    // A selection fetched using old credentials must not be saved accidentally.
    setModel(config?.model || '');
    setVisionModel(config?.vision_model || '');
  };

  useEffect(() => {
    if (!open) return;
    setBaseUrl(config?.base_url || '');
    setModel(config?.model || '');
    setVisionModel(config?.vision_model || '');
    setApiKey('');
    setHaBaseUrl(config?.home_assistant?.base_url || '');
    setHaToken('');
    setHaAllowedEntities(config?.home_assistant?.allowed_entities || '');
    setHaRequestTimeout(String(config?.home_assistant?.request_timeout || 10));
    setError('');
    setModelSearch('');
    void loadModels(config?.base_url || '', '');
    return () => modelRequest.current?.abort();
  }, [open, config, loadModels]);

  const matchingModels = models.filter((item) => item.id.toLowerCase().includes(modelSearch.trim().toLowerCase()));
  const optionsFor = (selected: string) => {
    const options = matchingModels.map((item) => item.id);
    if (selected && !options.includes(selected)) options.unshift(selected);
    return options;
  };
  const modelLabel = (id: string) => modelsReady && !models.some((item) => item.id === id)
    ? `${id}（当前配置，接口未列出）` : id;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError('');
    setSaving(true);
    try {
      const payload: ConfigUpdatePayload = {
        base_url: baseUrl.trim(),
        model: model.trim(),
        vision_model: visionModel.trim(),
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
          <input className="skill-input" autoComplete="off" placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1" value={baseUrl} onChange={(event) => { setBaseUrl(event.target.value); invalidateModels(); }} />
        </label>
        <label className="field-label">
          API KEY
          <input className="skill-input" type="password" autoComplete="new-password" placeholder="留空则保留当前密钥" value={apiKey} onChange={(event) => { setApiKey(event.target.value); invalidateModels(); }} />
        </label>
        <div className="model-catalog-status">
          <span role="status">{modelsLoading ? '正在获取可用模型…' : modelsReady ? `API 返回 ${models.length} 个模型${models.length ? '' : '，请检查账号权限'}` : '从 API 获取可用模型后选择'}</span>
          <button className="modal-secondary" type="button" disabled={modelsLoading || saving || !baseUrl.trim()} onClick={() => void loadModels(baseUrl, apiKey)}>
            {modelsLoading ? '获取中…' : '刷新模型列表'}
          </button>
        </div>
        {modelsError ? <div className="skill-form-error" role="alert">{modelsError}</div> : null}
        {models.length ? (
          <label className="field-label">
            搜索可用模型
            <input className="skill-input" type="search" placeholder="输入模型名称筛选" value={modelSearch} onChange={(event) => setModelSearch(event.target.value)} />
          </label>
        ) : null}
        <label className="field-label">
          主模型
          <select className="skill-input" value={model} disabled={modelsLoading || !modelsReady || !models.length} onChange={(event) => setModel(event.target.value)}>
            {!model ? <option value="" disabled>请选择主模型</option> : null}
            {optionsFor(model).map((id) => <option key={id} value={id}>{modelLabel(id)}</option>)}
          </select>
        </label>
        <label className="field-label">
          视觉模型
          <select className="skill-input" value={visionModel} disabled={modelsLoading || !modelsReady || !models.length} onChange={(event) => setVisionModel(event.target.value)}>
            <option value="">跟随主模型（支持多模态时无需单独选择）</option>
            {optionsFor(visionModel).map((id) => <option key={id} value={id}>{modelLabel(id)}</option>)}
          </select>
        </label>
        <div className="model-catalog-hint">视觉模型请选择支持图片输入的模型；列表由 API 提供，保存后对所有用户的新请求生效。</div>
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
            placeholder={'switch.desk_lamp|书桌插座|low\nswitch.water_heater|热水器|risk=high\nlight.living_room|客厅灯|客厅主灯'}
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
          <button className="modal-primary" type="submit" disabled={saving || modelsLoading || !model.trim()}>
            保存
          </button>
        </div>
      </form>
    </Modal>
  );
}
