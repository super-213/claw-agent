import type { TaskMention } from '../../api/tasks';

export function mentionBoundary(text: string, position: number) {
  if (position && !/\s/.test(text[position - 1])) return false;
  let quote = '';
  const closing: Record<string, string> = { '"': '"', "'": "'", '“': '”', '‘': '’', '`': '`' };
  for (let index = 0; index < position; index++) {
    const char = text[index];
    if (quote) { if (char === quote) quote = ''; }
    else if (closing[char] && (['`', '“', '‘'].includes(char) || index === 0 || /\s/.test(text[index - 1]))) quote = closing[char];
  }
  return !quote;
}

/** A deleted, moved or edited tag never retains an invisible member assignment. */
export function validMentions(text: string, mentions: TaskMention[]) {
  const command = /^\/ (家庭日程|家庭备忘|日程|备忘)(?: |$)/.exec(text);
  if (!command) return [];
  return mentions.filter(m => m.start >= command[0].length && mentionBoundary(text, m.start)
    && text.slice(m.start, m.end) === `@ ${m.label}` && (m.end === text.length || /\s/.test(text[m.end])))
    .sort((a, b) => a.start - b.start);
}
