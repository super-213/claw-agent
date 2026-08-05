import type { MessageMedia, MessageUsage } from '../api/types';

export const formatTime = (value?: string | null): string => {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
};

export const formatNumber = (value: unknown): string => {
  const number = Number(value || 0);
  if (number >= 100000000) return `${(number / 100000000).toFixed(1)}亿`;
  if (number >= 1000000) return `${(number / 1000000).toFixed(1)}M`;
  if (number >= 10000) return `${(number / 10000).toFixed(1)}万`;
  return new Intl.NumberFormat('zh-CN').format(Math.round(number));
};

export const formatTokens = (value: unknown): string => {
  const tokens = Number(value || 0);
  if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(1)}M`;
  if (tokens >= 1000) return `${(tokens / 1000).toFixed(1)}K`;
  return String(tokens);
};

export const formatUsage = (usage?: MessageUsage | null): string => {
  if (!usage) return '';
  const parts = [
    `tokens ${formatTokens(usage.total_tokens)}`,
    `cum ${formatTokens(usage.cumulative_tokens)}`,
  ];
  if (usage.tool_tokens) parts.push(`tool ${formatTokens(usage.tool_tokens)}`);
  if (usage.category) parts.push(String(usage.category));
  return parts.join(' · ');
};

export const formatBytes = (bytes: number): string => {
  const value = Number(bytes) || 0;
  if (value < 1024) return `${value}B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)}KB`;
  return `${(value / (1024 * 1024)).toFixed(1)}MB`;
};

export const formatElapsed = (ms: number): string => {
  const value = Number(ms);
  if (!Number.isFinite(value) || value < 0) return '';
  if (value < 1000) return `${Math.round(value)}ms`;
  if (value < 60_000) return `${(value / 1000).toFixed(value < 10_000 ? 2 : 1)}s`;
  const minutes = Math.floor(value / 60_000);
  const seconds = Math.round((value % 60_000) / 1000);
  return `${minutes}m${seconds}s`;
};

export const escapeHtml = (text: unknown): string =>
  String(text ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');

const IMAGE_EXT_RE = /\.(png|jpe?g|gif|webp|avif|svg)(?:[?#].*)?$/i;
const LOCAL_IMAGE_PREFIXES = ['/generated/', '/assets/', '/images/', '/static/', '/uploads/'];

export const imageSourceFrom = (item: string | MessageMedia | undefined): string => {
  if (!item) return '';
  if (typeof item === 'string') return item.trim();
  return String(item.url || item.src || item.path || '').trim();
};

const hasUnsafeLocalPath = (value: string): boolean => {
  if (value.includes('\\')) return true;
  try {
    return decodeURIComponent(value).includes('..');
  } catch {
    return value.includes('..');
  }
};

export const looksLikeImageSource = (source: unknown): boolean => {
  const raw = String(source || '').trim();
  if (!raw) return false;
  try {
    const url = new URL(raw);
    return IMAGE_EXT_RE.test(url.pathname);
  } catch {
    return IMAGE_EXT_RE.test(raw);
  }
};

export const safeImageSrc = (source: unknown): string => {
  const raw = String(source || '').trim();
  if (!raw || raw.includes('\\') || raw.startsWith('//')) return '';

  const withSlash = raw.replace(/^\.?\//, '');
  if (/^generated\//i.test(withSlash)) {
    if (hasUnsafeLocalPath(withSlash)) return '';
    return `/${encodeURI(withSlash)}`;
  }

  if (raw.startsWith('/')) {
    if (hasUnsafeLocalPath(raw)) return '';
    if (LOCAL_IMAGE_PREFIXES.some((prefix) => raw.startsWith(prefix)) || IMAGE_EXT_RE.test(raw)) {
      return encodeURI(raw);
    }
    return '';
  }

  try {
    const url = new URL(raw);
    if (url.protocol === 'http:' || url.protocol === 'https:') return url.href;
  } catch {
    if (!hasUnsafeLocalPath(raw) && IMAGE_EXT_RE.test(raw)) {
      return encodeURI(`/${raw.replace(/^\/+/, '')}`);
    }
  }

  return '';
};

export const isImageAttachment = (item: MessageMedia): boolean => {
  const type = String(item?.type || item?.mime_type || item?.mimeType || '').toLowerCase();
  const source = imageSourceFrom(item);
  return type.startsWith('image/') || looksLikeImageSource(source);
};

export const messageImageAlt = (item: string | MessageMedia): string => {
  if (!item || typeof item === 'string') return 'message image';
  return item.alt || item.title || item.name || 'message image';
};
