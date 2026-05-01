export const formatTime = (value) => {
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

export const formatTokens = (value) => {
  const tokens = Number(value || 0);
  if (tokens >= 1000000) return (tokens / 1000000).toFixed(1) + 'M';
  if (tokens >= 1000) return (tokens / 1000).toFixed(1) + 'K';
  return String(tokens);
};

export const formatUsage = (usage) => {
  if (!usage) return '';
  const parts = [
    `tokens ${formatTokens(usage.total_tokens)}`,
    `cum ${formatTokens(usage.cumulative_tokens)}`,
  ];
  if (usage.tool_tokens) parts.push(`tool ${formatTokens(usage.tool_tokens)}`);
  if (usage.category) parts.push(usage.category);
  return parts.join(' · ');
};

export const escapeHtml = (text) => String(text ?? '')
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')
  .replace(/'/g, '&#039;');

export const hasMarker = (text, marker) => {
  const escaped = marker.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp(`^\\s*[\\[［]\\s*${escaped}\\s*[\\]］]`).test(text || '');
};

export const isFormatNudge = (text) => {
  if (!text) return false;
  return text.includes('请严格按照格式回复')
    && /[\[［]\s*命令\s*[\]］]/.test(text)
    && /[\[［]\s*完成\s*[\]］]/.test(text);
};

const IMAGE_EXT_RE = /\.(png|jpe?g|gif|webp|avif)(?:[?#].*)?$/i;
const LOCAL_IMAGE_PREFIXES = [
  '/generated/',
  '/assets/',
  '/images/',
  '/static/',
  '/uploads/',
];

export const imageSourceFrom = (item) => {
  if (!item) return '';
  if (typeof item === 'string') return item.trim();
  return String(item.url || item.src || item.path || '').trim();
};

const hasUnsafeLocalPath = (value) => {
  if (value.includes('\\')) return true;
  try {
    return decodeURIComponent(value).includes('..');
  } catch {
    return value.includes('..');
  }
};

export const looksLikeImageSource = (source) => {
  const raw = String(source || '').trim();
  if (!raw) return false;
  try {
    const url = new URL(raw);
    return IMAGE_EXT_RE.test(url.pathname);
  } catch {
    return IMAGE_EXT_RE.test(raw);
  }
};

export const safeImageSrc = (source) => {
  const raw = String(source || '').trim();
  if (!raw || raw.includes('\\') || raw.startsWith('//')) return '';

  const withSlash = raw.replace(/^\.?\//, '');
  if (/^generated\//i.test(withSlash)) {
    if (hasUnsafeLocalPath(withSlash)) return '';
    return '/' + encodeURI(withSlash);
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
    if (url.protocol === 'http:' || url.protocol === 'https:') {
      return url.href;
    }
  } catch {
    if (!hasUnsafeLocalPath(raw) && IMAGE_EXT_RE.test(raw)) {
      return encodeURI('/' + raw.replace(/^\/+/, ''));
    }
  }

  return '';
};

export const isImageAttachment = (item) => {
  const type = String(item?.type || item?.mime_type || item?.mimeType || '').toLowerCase();
  const source = imageSourceFrom(item);
  return type.startsWith('image/') || looksLikeImageSource(source);
};
