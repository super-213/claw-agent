import { useEffect, useRef, useState } from 'react';
import { ArrowDown, ArrowUp, ImagePlus, Plus, Trash2 } from 'lucide-react';
import { useAppStore } from '../../stores/appStore';
import { boardApi, boardAssetUrl, type BoardBlock, type BoardData, type BoardView } from '../../api/board';

type PendingImage = { id: number; file: File; error: string };
export function BoardFields({ value, onChange, members, timezone, disabled = false, onUploading }: {
  value: BoardData; onChange: (value: BoardData) => void; members: BoardView['members']; timezone: string;
  disabled?: boolean; onUploading: (pending: boolean) => void;
}) {
  const fileInput = useRef<HTMLInputElement>(null);
  const owner = useAppStore(state => state.currentUser?.id);
  const live = useRef(true);
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);
  const valueRef = useRef(value); valueRef.current = value;
  const ownerRef = useRef(0);
  const [pending, setPending] = useState<PendingImage[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => onUploading(uploading || pending.length > 0), [uploading, pending.length, onUploading]);
  const patch = (changes: Partial<BoardData>) => onChange({ ...valueRef.current, ...changes });
  const blocks = value.content_blocks;
  const changeBlock = (index: number, block: BoardBlock) => patch({ content_blocks: blocks.map((b, i) => i === index ? block : b) });
  const move = (from: number, to: number) => { const next = [...blocks]; [next[from], next[to]] = [next[to], next[from]]; patch({ content_blocks: next }); };
  const uploadImages = async (items: PendingImage[]) => {
    setUploading(true); onUploading(true); setError('');
    for (const item of items) {
      try {
        if (!['image/jpeg', 'image/png', 'image/webp'].includes(item.file.type)) throw new Error('支持 JPEG、PNG 和 WebP 图片。');
        if (item.file.size > 10 * 1024 * 1024) throw new Error('单张图片不能超过 10MiB。');
        const { asset_id } = await boardApi.upload(item.file);
        if (!live.current || useAppStore.getState().currentUser?.id !== owner) return;
        patch({ content_blocks: [...valueRef.current.content_blocks, { type: 'image', asset_id, alt: item.file.name }] });
        setPending(current => current.filter(p => p.id !== item.id));
      } catch (caught) {
        if (!live.current || useAppStore.getState().currentUser?.id !== owner) return;
        setPending(current => current.map(p => p.id === item.id ? { ...p, error: (caught as Error).message } : p));
      }
    }
    setUploading(false);
    // Failed images must be resolved or explicitly removed before publication.
  };
  const addFiles = (files: File[]) => {
    if (!files.length || disabled || uploading) return;
    if (blocks.filter(b => b.type === 'image').length + pending.length + files.length > 9) { setError('一张便笺最多添加 9 张图片。'); return; }
    const items = files.map(file => ({ id: ++ownerRef.current, file, error: '' }));
    setPending(current => [...current, ...items]);
    void uploadImages(items);
  };
  // datetime-local represents the household timezone, independently of browser timezone.
  const localTime = value.expires_at ? new Intl.DateTimeFormat('sv-SE', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(value.expires_at)).replace(' ', 'T') : '';
  const setLocalTime = (input: string) => {
    if (!input) { patch({ expires_at: null, duration_hours: null }); return; }
    const approximate = new Date(input + 'Z');
    // Resolve zone offset at the selected date, including DST transitions.
    const parts = new Intl.DateTimeFormat('en-US', { timeZone: timezone, timeZoneName: 'longOffset' }).formatToParts(approximate);
    const offset = parts.find(p => p.type === 'timeZoneName')?.value.replace('GMT', '') || '+00:00';
    const iso = new Date(input + (offset === '' ? '+00:00' : offset)).toISOString();
    patch({ expires_at: iso, duration_hours: null });
  };
  return <fieldset className="board-fields" disabled={disabled || uploading} onPaste={event => {
    const files = Array.from(event.clipboardData.files).filter(file => file.type.startsWith('image/'));
    if (files.length) { event.preventDefault(); addFiles(files); }
  }}>
    <label>标题（可选）<input aria-label="便笺标题" maxLength={120} value={value.title} onChange={e => patch({ title: e.target.value })} placeholder="给这张便笺起个名字" /></label>
    <div className="board-blocks">
      {(blocks.length ? blocks : [{ type: 'text', text: '' } as BoardBlock]).map((block, index) => <div className="board-edit-block" key={block.type === 'image' ? `${block.asset_id}:${index}` : index}>
        {block.type === 'text' ? <label>正文<textarea aria-label={`便笺正文 ${index + 1}`} value={block.text} rows={4} maxLength={10000} placeholder="写下想留下的话…" onChange={e => {
          if (!blocks.length) patch({ content_blocks: [{ type: 'text', text: e.target.value }] });
          else changeBlock(index, { ...block, text: e.target.value });
        }} /></label> : <img src={boardAssetUrl(block.asset_id)} alt={block.alt || '便笺图片'} />}
        {blocks.length > 0 && <div className="board-block-tools">
          <button type="button" disabled={disabled || uploading || index === 0} onClick={() => move(index, index - 1)} aria-label={`上移内容 ${index + 1}`}><ArrowUp size={14} /></button>
          <button type="button" disabled={disabled || uploading || index === blocks.length - 1} onClick={() => move(index, index + 1)} aria-label={`下移内容 ${index + 1}`}><ArrowDown size={14} /></button>
          <button type="button" onClick={() => patch({ content_blocks: blocks.filter((_, i) => i !== index) })} aria-label={`移除内容 ${index + 1}`}><Trash2 size={14} /></button>
        </div>}
      </div>)}
    </div>
    <div className="board-inline-actions">
      <button type="button" onClick={() => patch({ content_blocks: [...blocks, { type: 'text', text: '' }] })}><Plus size={15} />添加文字</button>
      <button type="button" onClick={() => fileInput.current?.click()}><ImagePlus size={16} />添加图片</button>
      <input ref={fileInput} type="file" hidden accept="image/jpeg,image/png,image/webp" multiple onChange={e => { addFiles(Array.from(e.target.files || [])); e.target.value = ''; }} />
      <small>可粘贴图片 · 最多 9 张，每张 10MiB</small>
    </div>
    {uploading && <p role="status">正在保存图片…</p>}
    {pending.map(item => <div className="board-upload-error" key={item.id}>
      <span>{item.file.name}：{item.error || '上传中'}</span>
      {item.error && <><button type="button" onClick={() => void uploadImages([item])}>重试上传</button><button type="button" onClick={() => setPending(current => current.filter(p => p.id !== item.id))}>移除失败图片</button></>}
    </div>)}
    {error && <p role="alert">{error}</p>}
    <label>共享给<select aria-label="便笺共享范围" value={value.audience_mode} onChange={e => patch({ audience_mode: e.target.value as BoardData['audience_mode'], recipient_ids: [] })}>
      <option value="selected">指定成员</option><option value="household">所有人（当前家庭）</option>
    </select></label>
    {value.audience_mode === 'selected' && <div className="board-members" role="group" aria-label="便笺接收人">
      {members.filter(m => m.status === 'active').map(m => <label key={m.member_id}><input type="checkbox" checked={value.recipient_ids.includes(m.member_id)} onChange={e => patch({ recipient_ids: e.target.checked ? [...value.recipient_ids, m.member_id] : value.recipient_ids.filter(id => id !== m.member_id) })} />{m.display_name}</label>)}
      {!value.recipient_ids.length && <small>选择一位或多位成员；草稿仅自己可见。</small>}
    </div>}
    <label>保留方式<select aria-label="便笺保留方式" value={value.retention_mode} onChange={e => patch({ retention_mode: e.target.value as BoardData['retention_mode'], expires_at: null, duration_hours: null })}>
      <option value="permanent">长期保留</option><option value="until">限时保留</option>
    </select></label>
    {value.retention_mode === 'until' && <div className="board-expiration">
      <div className="board-inline-actions">{[24, 72, 168].map(hours => <button key={hours} type="button" aria-pressed={value.duration_hours === hours} onClick={() => patch({ duration_hours: hours, expires_at: null })}>{hours / 24} 天</button>)}</div>
      {value.duration_hours && <small>从发布成功起保留 {value.duration_hours} 小时</small>}
      <label>截止时间（{timezone}）<input aria-label="便笺截止时间" type="datetime-local" value={localTime} onChange={e => setLocalTime(e.target.value)} /></label>
      <small>到期后自动销毁，无法恢复。</small>
    </div>}
  </fieldset>;
}
