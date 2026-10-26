import type { TaskInvocation } from './tasks';
import { formRequest, jsonRequest, streamRequest } from './client';
import type { ChatStreamEvent, MessageMedia, SessionDetail } from './types';

export interface ChatObjectContext {
  type: 'inventory_item' | 'family_task';
  id: string;
  title: string;
  source: string;
  location?: string;
}

export interface ChatPayload {
  objectContext?: ChatObjectContext;
  sessionId: string;
  message: string;
  attachments?: MessageMedia[];
  images?: MessageMedia[];
  signal?: AbortSignal;
  invocation?: TaskInvocation;
  requestId?: string;
}

export interface RunApprovalPayload {
  runId: string;
  approvalToken: string;
  approved: boolean;
  signal?: AbortSignal;
}

interface UploadResponse {
  media: MessageMedia[];
}

export interface UploadOptions {
  signal?: AbortSignal;
  onProgress?: (percent: number) => void;
}

export function uploadChatMedia(files: File[], options: UploadOptions = {}): Promise<UploadResponse> {
  if (!window.navigator.onLine) return Promise.reject(new Error('当前离线，请联网后上传。'));
  return new Promise((resolve, reject) => {
    const xhr = new window.XMLHttpRequest();
    xhr.open('POST', '/api/chat/uploads');
    xhr.timeout = 120000;
    const cleanup = () => options.signal?.removeEventListener('abort', cancel);
    const fail = (message: string) => { cleanup(); reject(new Error(message)); };
    const cancel = () => { xhr.abort(); fail('已取消上传'); };
    if (options.signal?.aborted) { fail('已取消上传'); return; }
    options.signal?.addEventListener('abort', cancel, { once: true });
    xhr.upload.onprogress = event => {
      if (event.lengthComputable) options.onProgress?.(Math.round(event.loaded / event.total * 100));
    };
    xhr.onload = () => {
      cleanup();
      let data: UploadResponse & { message?: string };
      try { data = JSON.parse(xhr.responseText); } catch { data = { media: [] }; }
      if (xhr.status === 401) window.dispatchEvent(new CustomEvent('claw-api-unauthorized'));
      if (xhr.status === 413) { reject(new Error('文件过大，请选择不超过 25 MiB 的文件。')); return; }
      if (xhr.status < 200 || xhr.status >= 300 || !data.media?.length) { reject(new Error(data.message || (xhr.status === 401 ? '登录已过期，请登录后重试上传。' : '上传失败，请重试。'))); return; }
      resolve(data);
    };
    xhr.onerror = () => fail('网络连接失败，请重试上传。');
    xhr.ontimeout = () => fail('上传超时，请检查网络后重试。');
    xhr.onabort = () => fail('已取消上传');
    const body = new FormData();
    files.forEach(file => body.append('files', file));
    xhr.send(body);
  });
}

const toWirePayload = ({
  sessionId,
  message,
  attachments = [],
  images = [],
  invocation,
  requestId,
  objectContext,
}: ChatPayload) => ({
  session_id: sessionId,
  message,
  attachments,
  images,
  invocation,
  request_id: requestId,
  object_context: objectContext,
  task_ref:
    objectContext?.type === 'family_task'
      ? { task_id: objectContext.id }
      : undefined,
});

export const chatApi = {
  uploadMedia: (files: File[], options?: UploadOptions) => {
    if (options) return uploadChatMedia(files, options);
    const formData = new FormData();
    files.forEach((file) => formData.append('files', file));
    return formRequest<UploadResponse>('/api/chat/uploads', formData);
  },
  send: (payload: ChatPayload) =>
    jsonRequest<SessionDetail>('/api/chat', {
      method: 'POST',
      body: JSON.stringify(toWirePayload(payload)),
      signal: payload.signal,
    }),
  stream: (payload: ChatPayload, onEvent: (event: ChatStreamEvent) => void) =>
    streamRequest('/api/chat/stream', {
      method: 'POST',
      body: JSON.stringify(toWirePayload(payload)),
      signal: payload.signal,
      onEvent,
    }),
  approveRun: (
    payload: RunApprovalPayload,
    onEvent: (event: ChatStreamEvent) => void,
  ) =>
    streamRequest(`/api/runs/${payload.runId}/approval`, {
      method: 'POST',
      body: JSON.stringify({
        approval_token: payload.approvalToken,
        approved: payload.approved,
      }),
      signal: payload.signal,
      onEvent,
    }),
  resumeRun: (
    runId: string,
    onEvent: (event: ChatStreamEvent) => void,
    signal?: AbortSignal,
  ) =>
    streamRequest(`/api/runs/${runId}/resume`, {
      method: 'POST',
      signal,
      onEvent,
    }),
};
