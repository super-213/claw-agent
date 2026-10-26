import { jsonRequest } from './client';

export type KnowledgeCollection = 'documents' | 'records';
export interface KnowledgeEntry {
  id: string;
  title: string;
  object_name: string;
  aliases: string[];
  owner_user_id: string;
  visibility: 'personal' | 'household';
  version: number;
  status: string;
  updated_at: string;
  filename?: string;
  content?: string;
  kind?: 'fact' | 'event' | 'preference';
  warnings?: string[];
  file_url?: string;
  source_url: string;
  source?: { session_id?: string; node_id?: string; filename?: string; text?: string };
  history?: { action: string; by: string; at: string }[];
  deletion_note?: string;
}
export interface KnowledgeMatch {
  id: string;
  collection: KnowledgeCollection;
  title: string;
  text: string;
  source_url: string;
  location: string;
  updated_at: string;
}
const root = '/api/knowledge';
export const operationId = () => window.crypto.randomUUID();
export const knowledgeApi = {
  list: (collection: KnowledgeCollection, query = '') => jsonRequest<{ items: KnowledgeEntry[] }>(`${root}/${collection}?include_outdated=true&q=${encodeURIComponent(query)}`),
  get: (collection: KnowledgeCollection, id: string) => jsonRequest<KnowledgeEntry>(`${root}/${collection}/${encodeURIComponent(id)}`),
  search: (query: string) => jsonRequest<{ items: KnowledgeMatch[] }>(`${root}/search?q=${encodeURIComponent(query)}`),
  saveDocument: (payload: { path: string; request_id: string; title?: string; object_name?: string; source_session_id?: string; source_node_id?: string; replace_id?: string; expected_version?: number }) =>
    jsonRequest<KnowledgeEntry>(`${root}/documents`, { method: 'POST', body: JSON.stringify(payload) }),
  saveRecord: (payload: { title: string; content: string; object_name: string; kind: string; request_id: string }) =>
    jsonRequest<KnowledgeEntry>(`${root}/records`, { method: 'POST', body: JSON.stringify(payload) }),
  change: (collection: KnowledgeCollection, row: KnowledgeEntry, patch: Record<string, unknown>, requestId = operationId()) =>
    jsonRequest<KnowledgeEntry>(`${root}/${collection}/${row.id}`, { method: 'PATCH', body: JSON.stringify({ expected_version: row.version, request_id: requestId, patch }) }),
  remove: (collection: KnowledgeCollection, row: KnowledgeEntry, requestId = operationId()) =>
    jsonRequest<KnowledgeEntry>(`${root}/${collection}/${row.id}`, { method: 'DELETE', body: JSON.stringify({ expected_version: row.version, request_id: requestId }) }),
  reprocess: (row: KnowledgeEntry, requestId = operationId()) => jsonRequest<KnowledgeEntry>(`${root}/documents/${row.id}/reprocess`,
    { method: 'POST', body: JSON.stringify({ expected_version: row.version, request_id: requestId }) }),
};
