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
  uploadMedia: (files: File[]) => {
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
