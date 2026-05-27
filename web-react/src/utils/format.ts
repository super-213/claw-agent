import type { Message, MessageMedia, MessageUsage } from '../api/types';

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

export const hasMarker = (text: string | undefined, marker: string): boolean => {
  const escaped = marker.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp(`^\\s*[\\[［]\\s*${escaped}\\s*[\\]］]`).test(text || '');
};

export const markerRegex = (marker: string): RegExp => {
  const escaped = marker.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp(`[\\[［]\\s*${escaped}\\s*[\\]］]`);
};

export const isFormatNudge = (text?: string): boolean =>
  Boolean(
    text &&
      text.includes('请严格按照格式回复') &&
      /[\[［]\s*命令\s*[\]］]/.test(text) &&
      /[\[［]\s*完成\s*[\]］]/.test(text),
  );

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

export const isToolCallMessage = (msg: Message): boolean =>
  msg?.role === 'assistant' && markerRegex('命令').test(msg.content || '');

export const isToolResultMessage = (msg: Message): boolean =>
  msg?.role === 'user' && markerRegex('执行完成').test(msg.content || '');

export const extractCommandFromContent = (content?: string): string => {
  const text = content || '';
  const match = markerRegex('命令').exec(text);
  if (!match) return '';
  let raw = text.slice(match.index + match[0].length).trim();
  if (!raw) return '';

  const lines = raw.split('\n');
  if (lines[0].trim().startsWith('```')) {
    const inner: string[] = [];
    for (let i = 1; i < lines.length; i += 1) {
      if (lines[i].trim().startsWith('```')) break;
      inner.push(lines[i]);
    }
    raw = inner.join('\n').trim();
  }

  const commandLines = raw.split('\n');
  if (!commandLines.length) return '';

  const firstLine = commandLines[0].trim();
  const heredocMatch = firstLine.match(/<<-?\s*(['"]?)([A-Za-z_][A-Za-z0-9_]*)\1/);
  if (!heredocMatch) return firstLine;

  const delimiter = heredocMatch[2];
  const collected = [commandLines[0]];
  for (let i = 1; i < commandLines.length; i += 1) {
    collected.push(commandLines[i]);
    if (commandLines[i].trim() === delimiter) break;
  }
  return collected.join('\n').trim();
};

export const extractToolOutput = (
  content?: string,
): { output: string; success: boolean | null; returnCode: number | null } => {
  const text = content || '';
  const match = markerRegex('执行完成').exec(text);
  if (!match) return { output: text, success: null, returnCode: null };
  const body = text.slice(match.index + match[0].length).trim();
  const failMatch = body.match(/^命令执行失败[，,]\s*退出码\s*(-?\d+)\s*[:：]\s*([\s\S]*)/);
  if (failMatch) {
    return { output: failMatch[2].trim(), success: false, returnCode: Number(failMatch[1]) };
  }
  if (body.startsWith('命令执行成功')) {
    const rest = body.replace(/^命令执行成功[，,：:\s]*/, '').trim();
    return { output: rest, success: true, returnCode: 0 };
  }
  return { output: body, success: true, returnCode: 0 };
};

export const messageImageAlt = (item: string | MessageMedia): string => {
  if (!item || typeof item === 'string') return 'message image';
  return item.alt || item.title || item.name || 'message image';
};
