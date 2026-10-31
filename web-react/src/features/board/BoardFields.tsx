import { useEffect, useRef, useState } from 'react';
import { ArrowDown, ArrowUp, ImagePlus, Plus, Trash2 } from 'lucide-react';
import { preparePhoto, MAX_ATTACHMENT_BYTES } from '../chat/preparePhoto';
import { HomeDialog } from '../../components/ui/HomeDialog';
import { readCardAttachments, writeCardAttachments } from '../interactive-cards/state';
import { useAppStore } from '../../stores/appStore';
import { boardApi, boardAssetUrl, type BoardBlock, type BoardData, type BoardView } from '../../api/board';

type PendingImage = { id: number; file: File; error: string; compress?: boolean; prepared?: File; stage?: 'queued' | 'compressing' | 'uploading' | 'saving' | 'cancelled' | 'failed'; progress?: number };
const fileSize = (bytes: number) => bytes >= 1024 * 1024 ? `${(bytes / (1024 * 1024)).toFixed(2)} MB` : `${Math.round(bytes / 1024)} KB`;
function LocalPhoto({ file, onPreview }: { file: File; onPreview?: () => void }) {
  const [url, setUrl] = useState('');
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    setFailed(false);
    if (typeof URL.createObjectURL !== 'function') return;
    const value = URL.createObjectURL(file); setUrl(value);
    return () => URL.revokeObjectURL(value);
  }, [file]);
  const picture = url && !failed ? <img src={url} alt={`所选图片：${file.name}`} onError={() => setFailed(true)} />
    : <span>本机暂不能预览此格式，文件仍已选中</span>;
  return onPreview ? <button className="board-photo-thumb" type="button" aria-label={`预览图片：${file.name}`} onClick={onPreview}>{picture}</button> : <div className="board-local-photo">{picture}</div>;
}
export function BoardFields({ value, onChange, members, timezone, disabled = false, onUploading, editKey }: {
  value: BoardData; onChange: (value: BoardData) => void; members: BoardView['members']; timezone: string;
  editKey: string; disabled?: boolean; onUploading: (pending: boolean) => void;
}) {
  const owner = useAppStore(state => state.currentUser?.id);
  const live = useRef(true);
  const generation = useRef(0);
  const controllers = useRef(new Map<number, AbortController>());
  const cancelled = useRef(new Set<number>());
  const uploadingRef = useRef(false);
  useEffect(() => { live.current = true; return () => { live.current = false; generation.current++; uploadingRef.current = false; controllers.current.forEach(controller => controller.abort()); }; }, []);
  const valueRef = useRef(value); valueRef.current = value;
  const restored = readCardAttachments<PendingImage[]>(editKey) || [];
  const ownerRef = useRef(Math.max(0, ...restored.map(item => item.id)));
  const [pending, setPendingState] = useState<PendingImage[]>(restored);
  const pendingRef = useRef(pending);
  const setPending = (update: (current: PendingImage[]) => PendingImage[]) => {
    const next = update(pendingRef.current); pendingRef.current = next;
    writeCardAttachments(editKey, next); setPendingState(next);
  };
  const [uploading, setUploading] = useState(false);
  const [compress, setCompress] = useState(true);
  const [summaries, setSummaries] = useState<Record<string, string>>({});
  const [error, setError] = useState('');
  const [selectionNotice, setSelectionNotice] = useState('');
  const [preview, setPreview] = useState<{ file?: File; url?: string } | null>(null);
  useEffect(() => onUploading(uploading || pending.length > 0), [uploading, pending.length, onUploading]);
  const patch = (changes: Partial<BoardData>) => {
    valueRef.current = { ...valueRef.current, ...changes };
    onChange(valueRef.current);
  };
  const blocks = value.content_blocks;
  const changeBlock = (index: number, block: BoardBlock) => patch({ content_blocks: blocks.map((b, i) => i === index ? block : b) });
  const move = (from: number, to: number) => { const next = [...blocks]; [next[from], next[to]] = [next[to], next[from]]; patch({ content_blocks: next }); };
  const updatePending = (id: number, changes: Partial<PendingImage>) => {
    if (live.current && useAppStore.getState().currentUser?.id === owner)
      setPending(current => current.map(item => item.id === id ? { ...item, ...changes } : item));
  };
  const cancelUpload = (id: number) => {
    cancelled.current.add(id); controllers.current.get(id)?.abort();
    updatePending(id, { stage: 'cancelled', error: '已取消上传，可重试或移除' });
  };
  const uploadImages = async (items: PendingImage[]) => {
    if (uploadingRef.current) return;
    const epoch = generation.current;
    const active = () => live.current && generation.current === epoch && useAppStore.getState().currentUser?.id === owner;
    uploadingRef.current = true;
    setUploading(true); onUploading(true); setError('');
    for (const item of items) {
      if (!active()) break;
      if (cancelled.current.has(item.id) || item.stage === 'cancelled') continue;
      const controller = new AbortController(); controllers.current.set(item.id, controller);
      try {
        updatePending(item.id, { stage: 'compressing', progress: 0, error: '' });
        if (item.file.size > MAX_ATTACHMENT_BYTES) throw new Error('原图不能超过 25 MiB，请选择较小图片。');
        const prepared = item.prepared || (await preparePhoto(item.file, item.compress !== false)).file;
        if (controller.signal.aborted) throw new DOMException('已取消上传', 'AbortError');
        if (!active()) break;
        if (!['image/jpeg', 'image/png', 'image/webp'].includes(prepared.type)) throw new Error('支持 JPEG、PNG、WebP，HEIC 照片需转换后上传。');
        if (prepared.size > 10 * 1024 * 1024) throw new Error('处理后的图片不能超过 10 MiB，请开启压缩或选择较小图片。');
        updatePending(item.id, { prepared, stage: 'uploading' });
        const result = await boardApi.upload(prepared, { signal: controller.signal, onProgress: (loaded, total) => {
          if (active() && !controller.signal.aborted) updatePending(item.id, { progress: Math.min(100, Math.floor(loaded / total * 100)), stage: loaded >= total ? 'saving' : 'uploading' });
        } });
        if (controller.signal.aborted) throw new DOMException('已取消上传', 'AbortError');
        const asset_id = result?.asset_id;
        if (typeof asset_id !== 'string' || !/^asset_[a-f0-9]{32}$/.test(asset_id)) throw new Error('图片未确认保存成功，请重试上传。');
        if (!active()) break;
        setSummaries(current => ({ ...current, [asset_id]: `${fileSize(item.file.size)} → ${fileSize(prepared.size)}` }));
        patch({ content_blocks: [...valueRef.current.content_blocks, { type: 'image', asset_id, alt: item.file.name }] });
        setPending(current => current.filter(p => p.id !== item.id));
      } catch (caught) {
        if (active()) updatePending(item.id, { stage: controller.signal.aborted ? 'cancelled' : 'failed', error: controller.signal.aborted ? '已取消上传，可重试或移除' : (caught as Error).message });
      } finally { if (controllers.current.get(item.id) === controller) controllers.current.delete(item.id); }
    }
    if (active()) { uploadingRef.current = false; setUploading(false); }
  };
  useEffect(() => {
    // An interrupted request is safe to repeat: image imports have stable IDs.
    if (pendingRef.current.length) void uploadImages([...pendingRef.current]);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const addFiles = (files: File[]) => {
    if (!files.length) { setError('未读取到所选图片，请重新选择，或从照片中导出 JPEG 后重试。'); return; }
    if (disabled || uploading) { setError('当前操作尚未完成，所选图片还没有加入便笺，请稍后重新选择。'); return; }
    if (blocks.filter(b => b.type === 'image').length + pending.length + files.length > 9) { setError('一张便笺最多添加 9 张图片。'); return; }
    // Mark the editor dirty before the first asynchronous upload completes.
    patch({});
    const items: PendingImage[] = files.map(file => ({ id: ++ownerRef.current, file, error: '', compress, stage: 'queued' }));
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
  return <><fieldset className="board-fields" disabled={disabled || uploading} onPaste={event => {
    const files = Array.from(event.clipboardData.files).filter(file => file.type.startsWith('image/'));
    if (files.length) { event.preventDefault(); addFiles(files); }
  }}>
    <label>标题（可选）<input aria-label="便笺标题" maxLength={120} value={value.title} onChange={e => patch({ title: e.target.value })} placeholder="给这张便笺起个名字" /></label>
    <div className="board-blocks">
      {(blocks.length ? blocks : [{ type: 'text', text: '' } as BoardBlock]).map((block, index) => <div className="board-edit-block" key={block.type === 'image' ? `${block.asset_id}:${index}` : index}>
        {block.type === 'text' ? <label>正文<textarea aria-label={`便笺正文 ${index + 1}`} value={block.text} rows={4} maxLength={10000} placeholder="写下想留下的话…" onChange={e => {
          if (!blocks.length) patch({ content_blocks: [{ type: 'text', text: e.target.value }] });
          else changeBlock(index, { ...block, text: e.target.value });
        }} /></label> : <img src={boardAssetUrl(block.asset_id, 640)} alt={block.alt || '便笺图片'} />}
        {blocks.length > 0 && <div className="board-block-tools">
          <button type="button" disabled={disabled || uploading || index === 0} onClick={() => move(index, index - 1)} aria-label={`上移内容 ${index + 1}`}><ArrowUp size={14} /></button>
          <button type="button" disabled={disabled || uploading || index === blocks.length - 1} onClick={() => move(index, index + 1)} aria-label={`下移内容 ${index + 1}`}><ArrowDown size={14} /></button>
          <button type="button" onClick={() => patch({ content_blocks: blocks.filter((_, i) => i !== index) })} aria-label={`移除内容 ${index + 1}`}><Trash2 size={14} /></button>
        </div>}
      </div>)}
    </div>
    <div className="board-inline-actions">
      <button type="button" onClick={() => patch({ content_blocks: [...blocks, { type: 'text', text: '' }] })}><Plus size={15} />添加文字</button>
      <label className="board-image-picker">
        <ImagePlus size={16} aria-hidden="true" /><span>添加图片</span>
        <input type="file" aria-label="添加图片" accept="image/*" multiple
          onClick={e => { e.currentTarget.value = ''; setSelectionNotice(''); }}
          onChange={e => { const files = Array.from(e.currentTarget.files || []); setSelectionNotice(`已读取 ${files.length} 张图片`); addFiles(files); }} />
      </label>
      <small>可粘贴图片 · 最多 9 张，处理后每张不超过 10 MiB</small>
      <label><input type="checkbox" checked={compress} onChange={event => setCompress(event.target.checked)} />上传前压缩图片（推荐，最长边 2048 像素）</label>
    </div>
  </fieldset>
    {selectionNotice && <p role="status">{selectionNotice}</p>}
    {(pending.length > 0 || blocks.some(block => block.type === 'image')) && <section className="board-photo-previews" aria-label="所选图片预览">
      <strong>图片预览</strong>
      <div className="board-photo-grid">
        {pending.map(item => <figure key={item.id}>
          <LocalPhoto file={item.file} onPreview={() => setPreview({ file: item.file })} />
          <figcaption>{item.file.name}<span role="status">{item.stage === 'cancelled' ? '已取消上传，图片尚未保存' : item.error ? '上传失败，图片尚未保存' : item.stage === 'compressing' ? '正在处理图片…' : item.stage === 'saving' ? '已传输 100%，等待服务器保存…' : item.stage === 'uploading' ? `正在上传 ${item.progress || 0}%` : '已选中，等待上传…'}</span>
            {item.prepared && <span>{fileSize(item.file.size)} → {fileSize(item.prepared.size)}</span>}
            {!item.error && item.stage !== 'queued' && <progress aria-label={`${item.file.name} 上传进度`} max={100} value={item.stage === 'compressing' ? undefined : item.progress || 0} />}
            {!item.error && <button type="button" disabled={disabled} onClick={() => cancelUpload(item.id)}>取消上传</button>}
          </figcaption>
        </figure>)}
        {blocks.filter((block): block is Extract<BoardBlock, {type: 'image'}> => block.type === 'image').map((block, index) => <figure key={`${block.asset_id}:${index}`}>
          <button className="board-photo-thumb" type="button" aria-label={`预览已保存图片 ${index + 1}`} onClick={() => setPreview({ url: boardAssetUrl(block.asset_id) })}><img src={boardAssetUrl(block.asset_id, 640)} alt={block.alt || '已保存图片'} /></button>
          <figcaption>{block.alt || '图片'}<span role="status">图片已上传，发布便笺后生效</span>{summaries[block.asset_id] && <span>{summaries[block.asset_id]}</span>}</figcaption>
        </figure>)}
      </div>
    </section>}
    {uploading && <p role="status">正在处理上传队列…<button type="button" onClick={() => pendingRef.current.forEach(item => cancelUpload(item.id))}>取消全部上传</button></p>}
    {pending.filter(item => item.error).map(item => <div className="board-upload-error" key={item.id}>
      <span>{item.file.name}：{item.error || '上传中'}</span>
      {item.error && <><button type="button" disabled={uploading || disabled} onClick={() => { cancelled.current.delete(item.id); void uploadImages([{ ...item, stage: 'queued' }]); }}>重试上传</button><button type="button" disabled={disabled} onClick={() => setPending(current => current.filter(p => p.id !== item.id))}>移除失败图片</button></>}
    </div>)}
    {error && <p role="alert">{error}</p>}
    <fieldset className="board-fields" disabled={disabled || uploading}><label>共享给<select aria-label="便笺共享范围" value={value.audience_mode} onChange={e => patch({ audience_mode: e.target.value as BoardData['audience_mode'], recipient_ids: [] })}>
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
  </fieldset>
    {preview && <HomeDialog title="图片预览" className="board-dialog" onClose={() => setPreview(null)} wide>
      {preview.file ? <LocalPhoto file={preview.file} /> : <img className="board-full-image" src={preview.url} alt="已保存图片预览" />}
    </HomeDialog>}
  </>;
}
