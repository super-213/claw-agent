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

const streamRequest = async (url, options = {}, onEvent = () => {}) => {
  const response = await fetch(url, {
    ...options,
    headers: {
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers || {}),
    },
  });

  if (!response.ok) {
    await parseJson(response);
    return null;
  }

  if (!response.body) {
    const data = await response.json();
    onEvent(data);
    return data;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let finalEvent = null;

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      const event = JSON.parse(trimmed);
      onEvent(event);
      if (event.type === 'done') finalEvent = event;
      if (event.type === 'error') {
        const error = new Error(event.message || '请求失败');
        error.data = event;
        throw error;
      }
    }
  }

  buffer += decoder.decode();
  const trimmed = buffer.trim();
  if (trimmed) {
    const event = JSON.parse(trimmed);
    onEvent(event);
    if (event.type === 'done') finalEvent = event;
    if (event.type === 'error') {
      const error = new Error(event.message || '请求失败');
      error.data = event;
      throw error;
    }
  }

  return finalEvent;
};

export const sessionsApi = {
  list: () => jsonRequest('/api/sessions'),
  create: () => jsonRequest('/api/sessions', { method: 'POST' }),
  get: (sessionId) => jsonRequest(`/api/sessions/${sessionId}`),
  delete: (sessionId) => jsonRequest(`/api/sessions/${sessionId}`, { method: 'DELETE' }),
  copy: (sessionId) => jsonRequest(`/api/sessions/${sessionId}/copy`, { method: 'POST' }),
  share: (sessionId) => jsonRequest(`/api/sessions/${sessionId}/share`),
  updateShare: (sessionId, payload) => jsonRequest(`/api/sessions/${sessionId}/share`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  }),
};

export const authApi = {
  bootstrapStatus: () => jsonRequest('/api/auth/bootstrap-status'),
  usernames: () => jsonRequest('/api/auth/usernames'),
  bootstrapAdmin: (payload) => jsonRequest('/api/auth/bootstrap-admin', {
    method: 'POST',
    body: JSON.stringify(payload),
  }),
  login: (payload) => jsonRequest('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify(payload),
  }),
  logout: () => jsonRequest('/api/auth/logout', { method: 'POST' }),
  me: () => jsonRequest('/api/auth/me'),
};

export const adminApi = {
  shareableUsers: () => jsonRequest('/api/users'),
  users: () => jsonRequest('/api/admin/users'),
  createUser: (payload) => jsonRequest('/api/admin/users', {
    method: 'POST',
    body: JSON.stringify(payload),
  }),
  updateUser: (userId, payload) => jsonRequest(`/api/admin/users/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  }),
  deleteUser: (userId) => jsonRequest(`/api/admin/users/${userId}`, { method: 'DELETE' }),
  resetPassword: (userId, password) => jsonRequest(`/api/admin/users/${userId}/reset-password`, {
    method: 'POST',
    body: JSON.stringify({ password }),
  }),
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
  stream: ({ sessionId, message, attachments = [], images = [] }, onEvent) => streamRequest('/api/chat/stream', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, message, attachments, images }),
  }, onEvent),
};

export const branchApi = {
  switch: (sessionId, targetNodeId) => jsonRequest(`/api/sessions/${sessionId}/switch`, {
    method: 'POST',
    body: JSON.stringify({ target_node_id: targetNodeId }),
  }),
  tree: (sessionId) => jsonRequest(`/api/sessions/${sessionId}/tree`),
  create: (sessionId, branchPointNodeId) => jsonRequest(`/api/sessions/${sessionId}/branch`, {
    method: 'POST',
    body: JSON.stringify({ branch_point_node_id: branchPointNodeId }),
  }),
  delete: (sessionId, nodeId) => jsonRequest(`/api/sessions/${sessionId}/branch/${nodeId}`, {
    method: 'DELETE',
  }),
};
