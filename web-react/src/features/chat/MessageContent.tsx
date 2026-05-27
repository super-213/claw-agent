import type { Message, MessageMedia } from '../../api/types';
import { imageSourceFrom, isImageAttachment, messageImageAlt, safeImageSrc } from '../../utils/format';
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

export function MessageContent({ message }: { message: Message }) {
  const images = collectMessageImages(message);
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
    </>
  );
}
