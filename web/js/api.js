const parseJson = async (response) => {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.message || data.error || '请求失败');
    error.response = response;
    error.data = data;
    throw error;
  }
  return data;
};

const jsonRequest = (url, options = {}) => fetch(url, {
  ...options,
  headers: {
    ...(options.body ? { 'Content-Type': 'application/json' } : {}),
    ...(options.headers || {}),
  },
}).then(parseJson);

export const sessionsApi = {
  list: () => jsonRequest('/api/sessions'),
  create: () => jsonRequest('/api/sessions', { method: 'POST' }),
  get: (sessionId) => jsonRequest(`/api/sessions/${sessionId}`),
  delete: (sessionId) => jsonRequest(`/api/sessions/${sessionId}`, { method: 'DELETE' }),
  copy: (sessionId) => jsonRequest(`/api/sessions/${sessionId}/copy`, { method: 'POST' }),
};

export const skillsApi = {
  list: () => jsonRequest('/api/skills'),
  reload: () => jsonRequest('/api/skills/reload', { method: 'POST' }),
  create: ({ name, content }) => jsonRequest('/api/skills', {
    method: 'POST',
    body: JSON.stringify({ name, content }),
  }),
};

export const configApi = {
  get: () => jsonRequest('/api/config'),
  update: (payload) => jsonRequest('/api/config', {
    method: 'POST',
    body: JSON.stringify(payload),
  }),
};

export const chatApi = {
  send: ({ sessionId, message, attachments = [], images = [] }) => jsonRequest('/api/chat', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, message, attachments, images }),
  }),
};
