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
