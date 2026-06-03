import { FileText } from 'lucide-react';
import type { Message, MessageMedia } from '../../api/types';
import { formatBytes, imageSourceFrom, isImageAttachment, messageImageAlt, safeImageSrc } from '../../utils/format';
import { markdownToHtml } from '../../utils/markdown';

const collectMessageImages = (msg: Message) => {
  const images = Array.isArray(msg.images) ? msg.images : [];
  const attachments = Array.isArray(msg.attachments) ? msg.attachments : [];
  return [
    ...images,
    ...attachments.filter((item): item is MessageMedia => typeof item !== 'string' && isImageAttachment(item)),
  ]
    .map((item) => ({
      src: safeImageSrc(imageSourceFrom(item)),
      alt: messageImageAlt(item),
    }))
    .filter((item) => item.src);
};

const safeAttachmentHref = (source: unknown): string => {
  const raw = String(source || '').trim();
  if (!raw || raw.includes('\\') || raw.startsWith('//')) return '';
  if (raw.startsWith('/generated/') || raw.startsWith('/files/')) return encodeURI(raw);
  try {
    const url = new URL(raw);
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : '';
  } catch {
    return '';
  }
};

const collectMessageFiles = (msg: Message) => {
  const attachments = Array.isArray(msg.attachments) ? msg.attachments : [];
  return attachments
    .filter((item): item is MessageMedia => typeof item !== 'string' && !isImageAttachment(item))
    .map((item) => ({
      href: safeAttachmentHref(imageSourceFrom(item)),
      name: item.name || item.title || imageSourceFrom(item) || '附件',
      size: typeof item.size === 'number' ? formatBytes(item.size) : '',
      type: String(item.type || item.mime_type || item.mimeType || ''),
    }))
    .filter((item) => item.href);
};

export function MessageContent({ message }: { message: Message }) {
  const images = collectMessageImages(message);
  const files = collectMessageFiles(message);
  return (
    <>
      {message.content ? (
        <div className="message-text markdown-body" dangerouslySetInnerHTML={{ __html: markdownToHtml(message.content) }} />
      ) : null}
      {images.length ? (
        <div className="message-images">
          {images.map((image) => (
            <a key={image.src} className="message-image-link" href={image.src} target="_blank" rel="noopener noreferrer">
              <img src={image.src} alt={image.alt} loading="lazy" decoding="async" />
            </a>
          ))}
        </div>
      ) : null}
      {files.length ? (
        <div className="message-attachments">
          {files.map((file) => (
            <a key={file.href} className="message-attachment-link" href={file.href} target="_blank" rel="noopener noreferrer">
              <FileText size={16} />
              <span>{file.name}</span>
              {file.size || file.type ? <small>{[file.size, file.type].filter(Boolean).join(' · ')}</small> : null}
            </a>
          ))}
        </div>
      ) : null}
    </>
  );
}
