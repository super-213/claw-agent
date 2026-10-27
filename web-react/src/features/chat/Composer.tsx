import { BoardMentionInput } from '../board/BoardMentionInput';
import '../board/board.css';
import { Camera, FileText, Image as ImageIcon, Loader2, Paperclip, Send, X } from 'lucide-react';
import { KeyboardEvent, useEffect, useRef, useState } from 'react';
import { commandFromText, invocationFor, tasksApi, type FamilyMember, type TaskInvocation, type TaskMention } from '../../api/tasks';
import { TaskCommandInput } from '../tasks/TaskCommandInput';
import { validMentions } from '../tasks/taskSyntax';
import { useAppStore } from '../../stores/appStore';
import type { MessageMedia } from '../../api/types';
import { formatBytes, safeImageSrc } from '../../utils/format';
import { BottomSheet } from '../../components/ui/BottomSheet';
import { beginActivity } from '../pwa/activity';
import { useOnline } from '../pwa/useOnline';
import { MAX_ATTACHMENT_BYTES, MAX_ATTACHMENTS, preparePhoto } from './preparePhoto';
import type { UploadOptions } from '../../api/chat';

interface Attachment {
  id: number;
  file: File;
  preview?: string;
  media?: MessageMedia;
  status: 'waiting' | 'processing' | 'uploading' | 'ready' | 'error';
  progress: number;
  error?: string;
  note?: string;
}

export function Composer({
  disabled,
  draft,
  onDraftChange,
  onSend,
  onUploadFiles,
}: {
  disabled: boolean;
  draft: string;
  onDraftChange: (value: string) => void;
  onSend: (text: string, media: MessageMedia[], invocation?: TaskInvocation) => void | boolean | Promise<void | boolean>;
  onUploadFiles: (files: File[], options?: UploadOptions) => Promise<MessageMedia[]>;
}) {
  const userId = useAppStore(s => s.currentUser?.id);
  const [members, setMembers] = useState<FamilyMember[]>([]);
  const [mentions, setMentions] = useState<TaskMention[]>([]);
  const [invocation, setInvocation] = useState<TaskInvocation | null>(null);
  useEffect(() => {
    let active = true;
    setMembers([]); setMentions([]); setInvocation(null);
    void tasksApi.members().then(r => { if (active) setMembers(r.members); }).catch(() => undefined);
    return () => { active = false; };
  }, [userId]);
  const ref = useRef<HTMLTextAreaElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const photoInputRef = useRef<HTMLInputElement | null>(null);
  const cameraInputRef = useRef<HTMLInputElement | null>(null);
  const [items, setItems] = useState<Attachment[]>([]);
  const itemsRef = useRef(items);
  itemsRef.current = items;
  const controllers = useRef(new Map<number, AbortController>());
  const nextId = useRef(0);
  const live = useRef(true);
  const [sheet, setSheet] = useState(false);
  const [compress, setCompress] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const online = useOnline();
  const sending = useRef(false);
  const uploading = items.some(item => ['waiting', 'processing', 'uploading'].includes(item.status));
  const media = items.flatMap(item => item.media ? [item.media] : []);
  const patch = (id: number, update: Partial<Attachment>) => {
    if (live.current) setItems(current => current.map(item => item.id === id ? { ...item, ...update } : item));
  };

  useEffect(() => {
    live.current = true;
    const activeControllers = controllers.current;
    return () => {
      live.current = false;
      activeControllers.forEach(controller => controller.abort());
      itemsRef.current.forEach(item => { if (item.preview) URL.revokeObjectURL(item.preview); });
    };
  }, []);
  useEffect(() => items.length ? beginActivity() : undefined, [items.length]);
  const [canUseEnterToSend, setCanUseEnterToSend] = useState(true);

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return;
    const query = window.matchMedia('(hover: none), (pointer: coarse)');
    const updateInputMode = () => setCanUseEnterToSend(!query.matches);
    updateInputMode();
    if (query.addEventListener) {
      query.addEventListener('change', updateInputMode);
      return () => query.removeEventListener('change', updateInputMode);
    }
    query.addListener?.(updateInputMode);
    return () => query.removeListener?.(updateInputMode);
  }, []);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const resize = () => {
      el.style.height = 'auto';
      el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
    };
    resize();
    if (typeof ResizeObserver === 'undefined') return;
    let width = el.getBoundingClientRect().width;
    const observer = new ResizeObserver(([entry]) => {
      if (entry.contentRect.width === width) return;
      width = entry.contentRect.width;
      resize();
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [draft, disabled]);

  const send = async () => {
    const trimmed = draft.trimEnd();
    if ((!trimmed && !media.length) || disabled || uploading || !online || sending.current || items.some(item => item.status !== 'ready')) return;
    const mediaToSend = media;
    sending.current = true;
    onDraftChange('');
    const command = commandFromText(trimmed);
    const selected = command ? { ...(invocation?.command === command ? invocation : invocationFor(command)), mentions: validMentions(trimmed, mentions) } : undefined;
    setMentions([]); setInvocation(null);
    try {
      const result = selected ? await onSend(trimmed, mediaToSend, selected) : await onSend(trimmed, mediaToSend);
      if (result === false) { onDraftChange(trimmed); setUploadError('发送未完成，附件已保留。请先核对会话中的结果。'); }
      else {
        items.forEach(item => { if (item.preview) URL.revokeObjectURL(item.preview); });
        setItems([]); setUploadError('');
      }
    } catch (error) {
      onDraftChange(trimmed); setUploadError((error as Error).message || '发送失败，内容已保留。');
    } finally { sending.current = false; }
  };

  const upload = async (item: Attachment) => {
    const controller = new AbortController();
    controllers.current.set(item.id, controller);
    patch(item.id, { status: 'processing', error: undefined, progress: 0 });
    try {
      const prepared = await preparePhoto(item.file, compress);
      if (controller.signal.aborted || !live.current) return;
      if (prepared.file.size > MAX_ATTACHMENT_BYTES) throw new Error('单个文件不能超过 25 MiB，请启用图片压缩或选择较小文件。');
      patch(item.id, { status: 'uploading', note: prepared.note });
      const uploaded = await onUploadFiles([prepared.file], { signal: controller.signal, onProgress: progress => patch(item.id, { progress }) });
      if (controller.signal.aborted || !live.current) return;
      if (!uploaded[0]) throw new Error('服务器未返回附件，请重试。');
      patch(item.id, { media: uploaded[0], status: 'ready', progress: 100 });
    } catch (caught) {
      patch(item.id, { status: 'error', error: (caught as Error).message || '上传失败，请重试。' });
    } finally { controllers.current.delete(item.id); }
  };
  const selectFiles = async (files: FileList | null) => {
    const selected = Array.from(files || []);
    [fileInputRef, photoInputRef, cameraInputRef].forEach(input => { if (input.current) input.current.value = ''; });
    if (!selected.length || disabled || uploading) return;
    if (items.length + selected.length > MAX_ATTACHMENTS) { setUploadError('一条消息最多添加 10 个附件。'); return; }
    const added: Attachment[] = selected.map(file => ({ id: ++nextId.current, file, preview: file.type.startsWith('image/') ? URL.createObjectURL(file) : undefined, status: 'waiting', progress: 0 }));
    itemsRef.current = [...itemsRef.current, ...added];
    setItems(itemsRef.current); setUploadError('');
    for (const item of added) {
      if (!live.current) break;
      if (!itemsRef.current.some(current => current.id === item.id)) continue;
      await upload(item);
    }
  };
  const removeMedia = (item: Attachment) => {
    controllers.current.get(item.id)?.abort();
    if (item.preview) URL.revokeObjectURL(item.preview);
    itemsRef.current = itemsRef.current.filter(current => current.id !== item.id);
    setItems(itemsRef.current);
  };

  const keyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.nativeEvent.isComposing) return;
    if (canUseEnterToSend && event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void send();
    }
  };

  return (
    <div className="composer-area">
      <BoardMentionInput text={draft} onChange={onDraftChange} members={members} disabled={!!disabled}>{({ handleBoardKey, menuId: boardMenuId, activeOptionId: boardOptionId }) => <TaskCommandInput
        text={draft}
        onChange={onDraftChange}
        members={members}
        mentions={mentions}
        onMentions={setMentions}
        invocation={invocation}
        onInvocation={setInvocation}
        disabled={disabled}
        onFocusInput={() => { ref.current?.focus(); }}
      >
        {({ handleKeyDown, menuId, activeOptionId }) => <>
          <label className="sr-only" htmlFor="composer-file-input">
            添加文件或图片
          </label>
          <input
            id="composer-file-input"
            ref={fileInputRef}
            className="composer-file-input"
            type="file"
            multiple
            onChange={(event) => void selectFiles(event.target.files)}
          />
          <input ref={photoInputRef} type="file" accept="image/*" multiple hidden aria-label="选择照片" onChange={event => void selectFiles(event.target.files)} />
          <input ref={cameraInputRef} type="file" accept="image/*" capture="environment" hidden aria-label="拍照" onChange={event => void selectFiles(event.target.files)} />
          <button
            className="attach-btn"
            title="添加文件或图片"
            type="button"
            disabled={disabled || uploading || !online}
            onClick={() => setSheet(true)}
          >
            {uploading ? <Loader2 size={20} className="spin-icon" /> : <Paperclip size={20} />}
          </button>
          <textarea
            ref={ref}
            aria-label="输入指令或问题"
            role="combobox"
            aria-autocomplete="list"
            aria-haspopup="listbox"
            aria-expanded={!!(boardMenuId || menuId)}
            aria-controls={boardMenuId || menuId}
            aria-activedescendant={boardOptionId || activeOptionId}
            className="composer-input"
            placeholder="发张图片、问问文件，或说“帮我记住…”"
            rows={1}
            enterKeyHint="enter"
            value={draft}
            disabled={disabled}
            onKeyDown={event => {
              if (event.nativeEvent.isComposing) return;
              if (!event.shiftKey && (handleBoardKey(event.key) || handleKeyDown(event.key))) { event.preventDefault(); return; }
              keyDown(event);
            }}
            onChange={(event) => { const text = event.target.value; setMentions(validMentions(text, mentions)); onDraftChange(text); }}
          />
          <button
            className="send-btn"
            aria-label="发送"
            title="发送 (Enter)"
            type="button"
            disabled={disabled || uploading || !online || items.some(item => item.status !== 'ready') || (!draft.trim() && !media.length)}
            onClick={() => void send()}
          >
            <Send size={20} />
          </button>
        </>}
      </TaskCommandInput>}</BoardMentionInput>
      {items.length ? (
        <div className="composer-attachments composer-upload-list" aria-live="polite">
          {items.map((attachment) => {
            const item = attachment.media;
            const isImage = attachment.file.type.startsWith('image/');
            const preview = attachment.preview || (item && isImage ? safeImageSrc(item.url || item.src || item.path) : '');
            return (
              <div className="composer-attachment" key={attachment.id}>
                {preview ? <img src={preview} alt={attachment.file.name} loading="lazy" onError={event => { event.currentTarget.style.display = 'none'; }} /> : isImage ? <ImageIcon size={16} /> : <FileText size={16} />}
                <span>{attachment.file.name}</span>
                <small>{formatBytes(typeof item?.size === 'number' ? item.size : attachment.file.size)} · {attachment.status === 'ready' ? attachment.note || '已上传' : attachment.status === 'processing' ? '处理中…' : attachment.status === 'waiting' ? '等待上传' : attachment.status === 'error' ? '上传失败' : attachment.progress === 100 ? '服务器处理中…' : `上传 ${attachment.progress}%`}</small>
                {attachment.error && <span className="composer-upload-error">{attachment.error}</span>}
                {attachment.status === 'error' && <button type="button" disabled={!online || uploading} onClick={() => void upload(attachment)}>重试</button>}
                <button type="button" title={attachment.status === 'uploading' ? '取消上传并移除' : '移除附件'} onClick={() => removeMedia(attachment)}>
                  <X size={14} />
                </button>
              </div>
            );
          })}
        </div>
      ) : null}
      {uploadError && <p className="composer-upload-error" role="alert">{uploadError}</p>}
      {sheet && <BottomSheet title="添加附件" onClose={() => setSheet(false)}>
        <button className="pwa-sheet-action" type="button" onClick={() => { cameraInputRef.current?.click(); setSheet(false); }}><Camera size={22} /> 拍照</button>
        <button className="pwa-sheet-action" type="button" onClick={() => { photoInputRef.current?.click(); setSheet(false); }}><ImageIcon size={22} /> 选择照片</button>
        <button className="pwa-sheet-action" type="button" onClick={() => { fileInputRef.current?.click(); setSheet(false); }}><FileText size={22} /> 选择文件</button>
        <label><input type="checkbox" checked={compress} onChange={event => setCompress(event.target.checked)} /> 压缩聊天图片，减少流量</label>
        <p className="composer-hint">压缩后发送 JPEG 副本，保存到资料时也会使用此副本。HEIC 照片会尝试转换为 JPEG。文档保持原文件。</p>
      </BottomSheet>}
      <div className="composer-hint">{canUseEnterToSend ? 'Enter 发送 · Shift+Enter 换行' : '点击发送按钮提交'}</div>
    </div>
  );
}
