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

const markerRegex = (marker) => {
  const escaped = marker.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp(`[\\[［]\\s*${escaped}\\s*[\\]］]`);
};

export const isFormatNudge = (text) => {
  if (!text) return false;
  return text.includes('请严格按照格式回复')
    && /[\[［]\s*命令\s*[\]］]/.test(text)
    && /[\[［]\s*完成\s*[\]］]/.test(text);
};

const IMAGE_EXT_RE = /\.(png|jpe?g|gif|webp|avif|svg)(?:[?#].*)?$/i;
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

/**
 * Detect if a stored message is a tool call (assistant with [命令] marker).
 */
export const isToolCallMessage = (msg) => {
  return msg?.role === 'assistant' && markerRegex('命令').test(msg.content || '');
};

/**
 * Detect if a stored message is a tool result (user with [执行完成] marker).
 */
export const isToolResultMessage = (msg) => {
  return msg?.role === 'user' && markerRegex('执行完成').test(msg.content || '');
};

/**
 * Extract the command string from a [命令] message content.
 * Mirrors the Python InputParser.extract_command logic (simplified).
 */
export const extractCommandFromContent = (content) => {
  const text = content || '';
  const match = markerRegex('命令').exec(text);
  if (!match) return '';
  let raw = text.slice(match.index + match[0].length).trim();
  if (!raw) return '';

  const lines = raw.split('\n');
  if (lines[0].trim().startsWith('```')) {
    const inner = [];
    for (let i = 1; i < lines.length; i++) {
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
  for (let i = 1; i < commandLines.length; i++) {
    collected.push(commandLines[i]);
    if (commandLines[i].trim() === delimiter) break;
  }
  return collected.join('\n').trim();
};

/**
 * Extract output text from a [执行完成] message content.
 */
export const extractToolOutput = (content) => {
  const text = content || '';
  const match = markerRegex('执行完成').exec(text);
  if (!match) return { output: text, success: null, returnCode: null };
  const body = text.slice(match.index + match[0].length).trim();

  // Try to parse "命令执行失败，退出码 X: ..." or "命令执行成功"
  const failMatch = body.match(/^命令执行失败[，,]\s*退出码\s*(-?\d+)\s*[:：]\s*([\s\S]*)/);
  if (failMatch) {
    return { output: failMatch[2].trim(), success: false, returnCode: Number(failMatch[1]) };
  }
  const successPrefix = body.startsWith('命令执行成功');
  if (successPrefix) {
    const rest = body.replace(/^命令执行成功[，,：:\s]*/, '').trim();
    return { output: rest, success: true, returnCode: 0 };
  }
  return { output: body, success: true, returnCode: 0 };
};
