import { configApi } from './api.js';
import { els } from './dom.js';
import { setStatus } from './messages.js';
import { state } from './state.js';
import { escapeHtml } from './utils.js';

export const renderConfigSummary = () => {
  const cfg = state.config || {};
  els.configSummary.innerHTML = `
    <span>API URL</span><span title="${escapeHtml(cfg.base_url || '')}">${escapeHtml(cfg.base_url || '-')}</span>
    <span>API KEY</span><span>${escapeHtml(cfg.api_key_masked || '<未设置>')}</span>
    <span>模型</span><span>${escapeHtml(cfg.model || '-')}</span>
  `;
};

export const loadConfig = async () => {
  try {
    state.config = await configApi.get();
  } catch (error) {
    console.warn('loadConfig:', error);
  }
};

export const openConfigModal = async () => {
  els.configFormError.textContent = '';
  await loadConfig();

  const cfg = state.config || {};
  els.configBaseUrlInput.value = cfg.base_url || '';
  els.configApiKeyInput.value = '';
  els.configModelInput.value = cfg.model || '';
  renderConfigSummary();

  els.configModal.classList.add('open');
  els.configModal.setAttribute('aria-hidden', 'false');
  setTimeout(() => els.configBaseUrlInput.focus(), 0);
};

export const closeConfigModal = () => {
  els.configModal.classList.remove('open');
  els.configModal.setAttribute('aria-hidden', 'true');
  els.configFormError.textContent = '';
  els.configApiKeyInput.value = '';
};

export const submitConfig = async (event) => {
  event.preventDefault();
  els.configFormError.textContent = '';
  els.configSaveBtn.disabled = true;

  try {
    const payload = {
      base_url: els.configBaseUrlInput.value.trim(),
      model: els.configModelInput.value.trim(),
    };
    const apiKey = els.configApiKeyInput.value.trim();
    if (apiKey) payload.api_key = apiKey;

    const data = await configApi.update(payload);
    state.config = data.config;
    renderConfigSummary();
    closeConfigModal();
    setStatus('配置已保存', false);
    setTimeout(() => setStatus('就绪', false), 1200);
  } catch (error) {
    els.configFormError.textContent = error.data?.message || '网络错误';
    console.warn('submitConfig:', error);
  } finally {
    els.configSaveBtn.disabled = false;
  }
};
