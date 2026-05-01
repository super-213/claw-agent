import { escapeHtml, safeImageSrc } from './utils.js';

const PLACEHOLDER_PREFIX = '\u0000md';
const PLACEHOLDER_SUFFIX = '\u0000';

const isFenceStart = (line) => /^\s*(```+|~~~+)/.test(line);

const isTableSeparator = (line) => {
  const trimmed = line.trim();
  if (!trimmed.includes('|')) return false;
  return /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$/.test(trimmed);
};

const isBlockStart = (line) => {
  const trimmed = line.trim();
  return !trimmed
    || isFenceStart(line)
    || /^#{1,6}\s+/.test(trimmed)
    || /^>\s?/.test(line)
    || /^([-*+])\s+/.test(trimmed)
    || /^\d+[.)]\s+/.test(trimmed)
    || /^(-{3,}|\*{3,}|_{3,})$/.test(trimmed);
};

const makePlaceholders = () => {
  const values = [];
  return {
    add(value) {
      const token = `${PLACEHOLDER_PREFIX}${values.length}${PLACEHOLDER_SUFFIX}`;
      values.push(value);
      return token;
    },
    restore(value) {
      return value.replace(/\u0000md(\d+)\u0000/g, (_, index) => values[Number(index)] ?? '');
    },
  };
};

const safeLinkHref = (href) => {
  const raw = String(href || '').trim();
  if (!raw) return '';
  if (/^(https?:|mailto:|tel:)/i.test(raw)) return raw;
  if (/^(#|\/(?!\/)|\.\/|\.\.\/)/.test(raw) && !raw.includes('\\')) return raw;
  return '';
};

const splitTableRow = (line) => {
  const trimmed = line.trim().replace(/^\|/, '').replace(/\|$/, '');
  return trimmed.split('|').map((cell) => cell.trim());
};

const IMAGE_MARKDOWN_RE = /^!\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)$/;

const isImageMarkdownOnly = (lines) => {
  const contentLines = lines.map((line) => line.trim()).filter(Boolean);
  return contentLines.length > 0 && contentLines.every((line) => IMAGE_MARKDOWN_RE.test(line));
};

const renderInline = (text) => {
  const placeholders = makePlaceholders();
  let value = String(text ?? '');

  value = value.replace(/`([^`]+)`/g, (_, code) => (
    placeholders.add(`<code>${escapeHtml(code)}</code>`)
  ));

  value = value.replace(/!\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g, (match, alt, src) => {
    const safeSrc = safeImageSrc(src);
    if (!safeSrc) return escapeHtml(match);
    return placeholders.add(
      `<img class="markdown-image" src="${escapeHtml(safeSrc)}" alt="${escapeHtml(alt)}" loading="lazy" decoding="async">`,
    );
  });

  value = value.replace(/\[([^\]]+)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g, (match, label, href) => {
    const safeHref = safeLinkHref(href);
    if (!safeHref) return escapeHtml(match);
    return placeholders.add(
      `<a href="${escapeHtml(safeHref)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)}</a>`,
    );
  });

  value = escapeHtml(value);
  value = value.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  value = value.replace(/__([^_]+)__/g, '<strong>$1</strong>');
  value = value.replace(/~~([^~]+)~~/g, '<del>$1</del>');
  value = value.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
  value = value.replace(/(^|[^_])_([^_\n]+)_/g, '$1<em>$2</em>');

  return placeholders.restore(value);
};

const renderParagraph = (lines) => {
  const html = lines.map((line) => renderInline(line)).join('<br>');
  return `<p>${html}</p>`;
};

const renderList = (lines, ordered) => {
  const items = lines.map((line) => {
    const marker = ordered ? /^\s*\d+[.)]\s+/ : /^\s*[-*+]\s+/;
    let content = line.replace(marker, '');
    const checked = /^\[[ xX]\]\s+/.exec(content);
    if (checked) {
      const isChecked = checked[0].toLowerCase().includes('x');
      content = content.slice(checked[0].length);
      return `<li class="task-list-item"><input type="checkbox" disabled${isChecked ? ' checked' : ''}> ${renderInline(content)}</li>`;
    }
    return `<li>${renderInline(content)}</li>`;
  }).join('');
  return `<${ordered ? 'ol' : 'ul'}>${items}</${ordered ? 'ol' : 'ul'}>`;
};

const renderTable = (headerLine, bodyLines) => {
  const headers = splitTableRow(headerLine);
  const rows = bodyLines.map(splitTableRow).filter((row) => row.length);
  const head = headers.map((cell) => `<th>${renderInline(cell)}</th>`).join('');
  const body = rows
    .map((row) => `<tr>${row.map((cell) => `<td>${renderInline(cell)}</td>`).join('')}</tr>`)
    .join('');
  return `<div class="markdown-table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
};

export const markdownToHtml = (markdown) => {
  const lines = String(markdown ?? '').replace(/\r\n?/g, '\n').split('\n');
  const blocks = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();

    if (!trimmed) {
      index += 1;
      continue;
    }

    if (isFenceStart(line)) {
      const fence = /^\s*(```+|~~~+)\s*([A-Za-z0-9_-]+)?/.exec(line);
      const marker = fence?.[1] || '```';
      const language = fence?.[2] || '';
      index += 1;
      const codeLines = [];
      while (index < lines.length && !lines[index].trim().startsWith(marker)) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      if (isImageMarkdownOnly(codeLines)) {
        blocks.push(renderParagraph(codeLines.map((codeLine) => codeLine.trim()).filter(Boolean)));
        continue;
      }
      const className = language ? ` class="language-${escapeHtml(language)}"` : '';
      blocks.push(`<pre><code${className}>${escapeHtml(codeLines.join('\n'))}</code></pre>`);
      continue;
    }

    const heading = /^(#{1,6})\s+(.+)$/.exec(trimmed);
    if (heading) {
      const level = heading[1].length;
      blocks.push(`<h${level}>${renderInline(heading[2])}</h${level}>`);
      index += 1;
      continue;
    }

    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      blocks.push('<hr>');
      index += 1;
      continue;
    }

    if (index + 1 < lines.length && line.includes('|') && isTableSeparator(lines[index + 1])) {
      const bodyLines = [];
      index += 2;
      while (index < lines.length && lines[index].trim() && lines[index].includes('|')) {
        bodyLines.push(lines[index]);
        index += 1;
      }
      blocks.push(renderTable(line, bodyLines));
      continue;
    }

    if (/^>\s?/.test(line)) {
      const quoteLines = [];
      while (index < lines.length && /^>\s?/.test(lines[index])) {
        quoteLines.push(lines[index].replace(/^>\s?/, ''));
        index += 1;
      }
      blocks.push(`<blockquote>${markdownToHtml(quoteLines.join('\n'))}</blockquote>`);
      continue;
    }

    if (/^\s*[-*+]\s+/.test(line)) {
      const listLines = [];
      while (index < lines.length && /^\s*[-*+]\s+/.test(lines[index])) {
        listLines.push(lines[index]);
        index += 1;
      }
      blocks.push(renderList(listLines, false));
      continue;
    }

    if (/^\s*\d+[.)]\s+/.test(line)) {
      const listLines = [];
      while (index < lines.length && /^\s*\d+[.)]\s+/.test(lines[index])) {
        listLines.push(lines[index]);
        index += 1;
      }
      blocks.push(renderList(listLines, true));
      continue;
    }

    const paragraph = [line];
    index += 1;
    while (index < lines.length && !isBlockStart(lines[index])) {
      paragraph.push(lines[index]);
      index += 1;
    }
    blocks.push(renderParagraph(paragraph));
  }

  return blocks.join('\n');
};
