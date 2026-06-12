import { FileText, Image as ImageIcon, Loader2, Paperclip, Send, X } from 'lucide-react';
import { KeyboardEvent, useEffect, useRef, useState } from 'react';
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
  onSend: (text: string, media: MessageMedia[]) => void | Promise<void>;
  onUploadFiles: (files: File[]) => Promise<MessageMedia[]>;
}) {
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
    const trimmed = draft.trim();
    if ((!trimmed && !media.length) || disabled || uploading) return;
    const mediaToSend = media;
    onDraftChange('');
    setMedia([]);
    await onSend(trimmed, mediaToSend);
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
      <div className="composer">
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
          className="composer-input"
          placeholder="输入指令或问题..."
          rows={1}
          enterKeyHint="enter"
          value={draft}
          disabled={disabled}
          onKeyDown={keyDown}
          onChange={(event) => onDraftChange(event.target.value)}
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
      </div>
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
