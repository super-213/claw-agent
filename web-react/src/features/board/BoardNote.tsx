import { useRef, useState, type ReactNode } from 'react';
import { ArrowUpRight, Clock3, UsersRound } from 'lucide-react';
import { boardAssetUrl, type BoardView } from '../../api/board';

import { boardTime } from './boardTime';
function BoardImage({ assetId, alt, onPreview }: { assetId: string; alt: string; onPreview: (assetId: string) => void }) {
  const [failed, setFailed] = useState(false);
  return failed ? <button type="button" className="board-image-failed" onClick={() => setFailed(false)}>图片暂不可用，点击重试</button> : <button type="button" className="board-image" aria-label="查看便笺图片" onClick={e => { e.stopPropagation(); onPreview(assetId); }}>
    <img src={boardAssetUrl(assetId)} alt={alt || '便笺图片'} loading="lazy" onError={() => setFailed(true)} />
  </button>;
}
export function BoardBody({ view, onPreview }: { view: BoardView; onPreview: (assetId: string) => void }) {
  return <>{view.post.title && <h3>{view.post.title}</h3>}{view.post.content_blocks.map((block, index) => block.type === 'text'
    ? <p key={index}>{block.text}</p>
    : <BoardImage key={`${block.asset_id}:${view.post.version}:${index}`} assetId={block.asset_id} alt={block.alt} onPreview={onPreview} />)}</>;
}
export function BoardNote({ view, onOpen, onPreview, dragHandle, compact = false }: { view: BoardView; onOpen: () => void; onPreview: (assetId: string) => void; dragHandle?: ReactNode; compact?: boolean }) {
  const { post, members, timezone } = view;
  const label = view.activity_kind === 'poll' ? '家庭投票' : view.activity_kind === 'relay' ? '家庭接龙' : '便笺';
  const pointer = useRef({ x: 0, y: 0, scrolled: false });
  const names = (ids: string[]) => ids.map(id => members.find(m => m.member_id === id)?.display_name || '家庭成员').join('、');
  return <article className={`board-paper board-note${compact ? ' board-note-compact' : ''}`} aria-label={`${label}：${post.title || '未命名便笺'}`} onPointerDown={event => { pointer.current = { x: event.clientX, y: event.clientY, scrolled: false }; }} onPointerCancel={() => { pointer.current.scrolled = true; }} onClick={event => {
    if (pointer.current.scrolled || Math.abs(event.clientX - pointer.current.x) + Math.abs(event.clientY - pointer.current.y) > 8) return;
    if ((event.target as HTMLElement).closest('button, a') || window.getSelection()?.toString()) return;
    onOpen();
  }}>
    <header className={`board-note-header${dragHandle ? ' has-drag-handle' : ''}`}>{dragHandle || <><span>{names([post.created_by])} {view.activity_kind ? label : '留言'}</span><time dateTime={post.published_at || post.created_at}>{boardTime(post.published_at || post.created_at, timezone)}</time></>}</header>
    <div className="board-note-body" tabIndex={compact ? undefined : 0} aria-label={compact ? '便笺摘要' : '便笺正文，可滚动'} onScroll={() => { pointer.current.scrolled = true; }}><BoardBody view={view} onPreview={compact ? () => onOpen() : onPreview} /></div>
    <footer className="board-note-footer">
      <span title={post.audience_mode === 'household' ? '当前家庭所有有效成员' : names(post.recipient_ids)}><UsersRound size={13} />{post.audience_mode === 'household' ? '所有人' : names(post.recipient_ids)}</span>
      <span><Clock3 size={13} />{post.state === 'expired' ? '已到期' : post.state === 'withdrawn' ? '已撤下' : post.expires_at ? compact ? '限时保留' : `${boardTime(post.expires_at, timezone)} 截止` : '长期保留'}</span>
      <button type="button" onClick={onOpen}>{compact ? '查看' : '查看详情'}<ArrowUpRight size={14} /></button>
    </footer>
  </article>;
}
