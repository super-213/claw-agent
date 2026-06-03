import { formRequest, jsonRequest, streamRequest } from './client';
import type { ChatStreamEvent, MessageMedia, SessionDetail } from './types';

export interface ChatPayload {
  sessionId: string;
  message: string;
  attachments?: MessageMedia[];
  images?: MessageMedia[];
  signal?: AbortSignal;
}

interface UploadResponse {
  media: MessageMedia[];
}

const toWirePayload = ({ sessionId, message, attachments = [], images = [] }: ChatPayload) => ({
  session_id: sessionId,
  message,
  attachments,
  images,
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
};
