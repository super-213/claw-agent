import { FileText, Image as ImageIcon, Loader2, Paperclip, Send, X } from 'lucide-react';
import { KeyboardEvent, useEffect, useRef, useState } from 'react';
import { commandFromText, invocationFor, tasksApi, type FamilyMember, type TaskInvocation, type TaskMention } from '../../api/tasks';
import { TaskCommandInput } from '../tasks/TaskCommandInput';
import { validMentions } from '../tasks/taskSyntax';
import { useAppStore } from '../../stores/appStore';
import type { MessageMedia } from '../../api/types';
import { formatBytes, safeImageSrc } from '../../utils/format';

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
  onSend: (text: string, media: MessageMedia[], invocation?: TaskInvocation) => void | Promise<void>;
  onUploadFiles: (files: File[]) => Promise<MessageMedia[]>;
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
  const [media, setMedia] = useState<MessageMedia[]>([]);
  const [uploading, setUploading] = useState(false);
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
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
  }, [draft]);

  const send = async () => {
    const trimmed = draft.trimEnd();
    if ((!trimmed && !media.length) || disabled || uploading) return;
    const mediaToSend = media;
    onDraftChange('');
    setMedia([]);
    const command = commandFromText(trimmed);
    const selected = command ? { ...(invocation?.command === command ? invocation : invocationFor(command)), mentions: validMentions(trimmed, mentions) } : undefined;
    setMentions([]); setInvocation(null);
    if (selected) await onSend(trimmed, mediaToSend, selected);
    else await onSend(trimmed, mediaToSend);
  };

  const selectFiles = async (files: FileList | null) => {
    const selected = Array.from(files || []);
    if (fileInputRef.current) fileInputRef.current.value = '';
    if (!selected.length || disabled || uploading) return;

    setUploading(true);
    try {
      const uploaded = await onUploadFiles(selected);
      setMedia((current) => [...current, ...uploaded]);
    } catch (caught) {
      alert(`上传失败: ${(caught as Error).message || '网络错误'}`);
    } finally {
      setUploading(false);
    }
  };

  const removeMedia = (index: number) => {
    setMedia((current) => current.filter((_, itemIndex) => itemIndex !== index));
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
      <TaskCommandInput
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
          <button
            className="attach-btn"
            title="添加文件或图片"
            type="button"
            disabled={disabled || uploading}
            onClick={() => fileInputRef.current?.click()}
          >
            {uploading ? <Loader2 size={20} className="spin-icon" /> : <Paperclip size={20} />}
          </button>
          <textarea
            ref={ref}
            aria-label="输入指令或问题"
            role="combobox"
            aria-autocomplete="list"
            aria-haspopup="listbox"
            aria-expanded={!!menuId}
            aria-controls={menuId}
            aria-activedescendant={activeOptionId}
            className="composer-input"
            placeholder="输入 / 空格选择日程或备忘，@ 空格选择成员"
            rows={1}
            enterKeyHint="enter"
            value={draft}
            disabled={disabled}
            onKeyDown={event => {
              if (event.nativeEvent.isComposing) return;
              if (!event.shiftKey && handleKeyDown(event.key)) { event.preventDefault(); return; }
              keyDown(event);
            }}
            onChange={(event) => { const text = event.target.value; setMentions(validMentions(text, mentions)); onDraftChange(text); }}
          />
          <button
            className="send-btn"
            title="发送 (Enter)"
            type="button"
            disabled={disabled || uploading || (!draft.trim() && !media.length)}
            onClick={() => void send()}
          >
            <Send size={20} />
          </button>
        </>}
      </TaskCommandInput>
      {media.length || uploading ? (
        <div className="composer-attachments" aria-live="polite">
          {media.map((item, index) => {
            const mimeType = String(item.type || item.mime_type || item.mimeType || '');
            const isImage = mimeType.startsWith('image/');
            const preview = isImage ? safeImageSrc(item.url || item.src || item.path) : '';
            return (
              <div className="composer-attachment" key={`${item.url || item.path || item.name}-${index}`}>
                {preview ? <img src={preview} alt={item.alt || item.name || 'upload'} /> : isImage ? <ImageIcon size={16} /> : <FileText size={16} />}
                <span>{item.name || item.title || item.url || '附件'}</span>
                {typeof item.size === 'number' ? <small>{formatBytes(item.size)}</small> : null}
                <button type="button" title="移除附件" onClick={() => removeMedia(index)}>
                  <X size={14} />
                </button>
              </div>
            );
          })}
          {uploading ? (
            <div className="composer-attachment pending">
              <Loader2 size={16} className="spin-icon" />
              <span>上传中...</span>
            </div>
          ) : null}
        </div>
      ) : null}
      <div className="composer-hint">{canUseEnterToSend ? 'Enter 发送 · Shift+Enter 换行' : '点击发送按钮提交'}</div>
    </div>
  );
}
