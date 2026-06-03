export const AUTO_SCROLL_BOTTOM_THRESHOLD = 80;

export function isNearBottom(
  node: Pick<HTMLDivElement, 'clientHeight' | 'scrollHeight' | 'scrollTop'>,
  threshold = AUTO_SCROLL_BOTTOM_THRESHOLD,
) {
  return node.scrollHeight - node.scrollTop - node.clientHeight <= threshold;
}
