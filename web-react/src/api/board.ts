import { uploadForm, type UploadOptions, jsonRequest } from './client';
import type { CardContext, CardView } from '../features/interactive-cards/types';

export type BoardBlock = { type: 'text'; text: string } | { type: 'image'; asset_id: string; alt: string };
export interface BoardData {
  title: string; content_blocks: BoardBlock[]; audience_mode: 'selected' | 'household'; recipient_ids: string[];
  retention_mode: 'permanent' | 'until'; expires_at: string | null; duration_hours: number | null;
}
export interface BoardPost extends BoardData {
  id: string; created_by: string; version: number; created_at: string; published_at?: string;
  state: 'draft' | 'active' | 'expired' | 'withdrawn'; missing_fields?: string[];
}
export interface BoardView extends CardView {
  activity_kind?: 'poll' | 'relay'; post: BoardPost; timezone: string; current_member_id: string;
  members: Array<{ member_id: string; display_name: string; status: string; aliases?: string[] }>;
}
export interface BoardList { items: BoardView[]; next_cursor: string | null; server_now: string }
export interface BoardAction { action: 'save' | 'withdraw' | 'save_draft' | 'publish'; data: Partial<BoardData>; expected_version: number; target: BoardView['resource'] }
export const emptyBoardData = (): BoardData => ({ title: '', content_blocks: [], audience_mode: 'selected', recipient_ids: [], retention_mode: 'permanent', expires_at: null, duration_hours: null });
export const boardData = (post: BoardData): BoardData => ({ title: post.title, content_blocks: post.content_blocks, audience_mode: post.audience_mode, recipient_ids: post.recipient_ids, retention_mode: post.retention_mode, expires_at: post.expires_at, duration_hours: post.duration_hours });
const base = '/api/home/board';
const sessionQuery = (context?: CardContext) => context?.sessionId ? `?session_id=${encodeURIComponent(context.sessionId)}` : '';
export const boardAssetUrl = (id: string, width = 1600) => `${base}/assets/${encodeURIComponent(id)}?width=${width}`;
export const boardApi = {
  feed: (cursor?: string | null) => jsonRequest<BoardList>(`${base}/feed?${new URLSearchParams(cursor ? { cursor } : {})}`, { cache: 'no-store' }),
  list: (cursor?: string | null) => jsonRequest<BoardList>(`${base}/posts?${new URLSearchParams(cursor ? { cursor } : {})}`, { cache: 'no-store' }),
  get: (id: string, draft = false, context?: CardContext) => jsonRequest<BoardView>(`${base}/${draft ? 'drafts' : 'posts'}/${encodeURIComponent(id)}${sessionQuery(context)}`, { cache: 'no-store' }),
  createDraft: (id: string, data = emptyBoardData()) => jsonRequest<BoardView>(`${base}/drafts`, { method: 'POST', body: JSON.stringify({ request_id: id, data }) }),
  mutate: (action: BoardAction, requestId: string, context?: CardContext) => {
    const draft = action.target.type === 'board_post_draft';
    const suffix = action.action === 'publish' ? '/commit' : action.action === 'withdraw' ? '/withdraw' : '';
    return jsonRequest<BoardView>(`${base}/${draft ? 'drafts' : 'posts'}/${encodeURIComponent(action.target.id)}${suffix}${sessionQuery(context)}`, {
      method: suffix ? 'POST' : 'PATCH', body: JSON.stringify({ request_id: requestId, expected_version: action.expected_version, data: action.data }),
    });
  },
  upload: (file: File, options?: UploadOptions) => { const data = new FormData(); data.append('file', file); return uploadForm<{ asset_id: string }>(`${base}/assets`, data, options); },
};
