export const NOTE_WIDTH = 280;
export const NOTE_HEIGHT = 320;
export const BOARD_PADDING = 24;
export const BOARD_WIDTH = 960;
export const MAX_BOARD_SIZE = 20000;
export interface NotePlacement { x: number; y: number; z: number }
export type BoardLayout = Record<string, NotePlacement>;
export const boardLayoutKey = (userId: string) => `claw.board.layout.v1.${userId}`;
export const boundPosition = (value: number, size: number) => Math.max(BOARD_PADDING, Math.min(MAX_BOARD_SIZE - size - BOARD_PADDING, value));

export function parseBoardLayout(raw: string | null): BoardLayout {
  try {
    const value: unknown = JSON.parse(raw || '{}');
    if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
    const result: BoardLayout = {};
    for (const [id, placement] of Object.entries(value)) {
      if (!placement || typeof placement !== 'object') continue;
      const { x, y, z } = placement as NotePlacement;
      if (![x, y, z].every(Number.isFinite) || z < 0 || z > 1000000) continue;
      Object.defineProperty(result, id, { enumerable: true, writable: true, configurable: true,
        value: { x: boundPosition(x, NOTE_WIDTH), y: boundPosition(y, NOTE_HEIGHT), z: Math.floor(z) } });
    }
    return result;
  } catch { return {}; }
}
export function arrangeBoard(ids: string[], columns = 3): BoardLayout {
  return Object.fromEntries(ids.map((id, index) => [id, {
    x: BOARD_PADDING + (index % columns) * (NOTE_WIDTH + BOARD_PADDING),
    y: BOARD_PADDING + Math.floor(index / columns) * (NOTE_HEIGHT + BOARD_PADDING), z: index + 1,
  }]));
}
export function ensurePlacements(layout: BoardLayout, ids: string[]): BoardLayout {
  let result = layout;
  let nextZ = Math.max(0, ...Object.values(layout).map(p => p.z));
  for (const id of ids) {
    if (Object.prototype.hasOwnProperty.call(result, id)) continue;
    const occupied = ids.filter(key => Object.prototype.hasOwnProperty.call(result, key)).map(key => result[key]);
    let index = 0;
    let placement: NotePlacement;
    do {
      placement = { x: BOARD_PADDING + (index % 3) * (NOTE_WIDTH + BOARD_PADDING),
        y: BOARD_PADDING + Math.floor(index / 3) * (NOTE_HEIGHT + BOARD_PADDING), z: ++nextZ };
      index++;
    } while (occupied.some(p => p.x < placement.x + NOTE_WIDTH && p.x + NOTE_WIDTH > placement.x
      && p.y < placement.y + NOTE_HEIGHT && p.y + NOTE_HEIGHT > placement.y));
    result = { ...result, [id]: placement };
  }
  return result;
}
export function bringToFront(layout: BoardLayout, id: string): BoardLayout {
  if (!Object.prototype.hasOwnProperty.call(layout, id)) return layout;
  const entries = Object.entries(layout).sort((a, b) => a[1].z - b[1].z);
  if (entries[entries.length - 1]?.[0] === id) return layout;
  // Compact ranks on activation, keeping CSS stacking values bounded.
  return Object.fromEntries([...entries.filter(([key]) => key !== id), [id, layout[id]] as [string, NotePlacement]]
    .map(([key, placement], index) => [key, placement.z === index + 1 ? placement : { ...placement, z: index + 1 }]));
}
export function placementInBoard(current: NotePlacement, bounds: { width: number; height: number }): NotePlacement {
  const x = boundPosition(Math.min(current.x, bounds.width - NOTE_WIDTH - BOARD_PADDING), NOTE_WIDTH);
  const y = boundPosition(Math.min(current.y, bounds.height - NOTE_HEIGHT - BOARD_PADDING), NOTE_HEIGHT);
  return current.x === x && current.y === y ? current : { ...current, x, y };
}
export function moveNote(layout: BoardLayout, id: string, x: number, y: number, bounds?: { width: number; height: number }): BoardLayout {
  if (!Object.prototype.hasOwnProperty.call(layout, id)) return layout;
  const current = layout[id];
  const next = { ...current, x: boundPosition(Math.min(x, bounds ? bounds.width - NOTE_WIDTH - BOARD_PADDING : x), NOTE_WIDTH), y: boundPosition(Math.min(y, bounds ? bounds.height - NOTE_HEIGHT - BOARD_PADDING : y), NOTE_HEIGHT) };
  return current.x === next.x && current.y === next.y ? layout : { ...layout, [id]: next };
}
