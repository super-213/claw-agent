export const widgetNames = {
  today: '今日日程',
  fridge: '冰箱',
  medicine: '药箱',
  memos: '我的备忘',
  attention: '需要关注',
  inventory: '家中物品',
  pantry: '食品柜',
} as const;
export type WidgetKind = keyof typeof widgetNames;
export type WidgetSize = 'small' | 'medium' | 'large';
export interface HomeWidget {
  kind: WidgetKind;
  size: WidgetSize;
}
export const defaultWidgets: HomeWidget[] = [
  { kind: 'today', size: 'small' },
  { kind: 'fridge', size: 'small' },
  { kind: 'medicine', size: 'small' },
  { kind: 'memos', size: 'small' },
  { kind: 'attention', size: 'medium' },
  { kind: 'inventory', size: 'medium' },
];
export const widgetStorageKey = (user: string) =>
  `claw.home.widgets.v1.${user}`;
export function parseWidgetLayout(raw: string | null): HomeWidget[] {
  if (!raw) return defaultWidgets.map((widget) => ({ ...widget }));
  try {
    const value: unknown = JSON.parse(raw);
    if (!Array.isArray(value)) throw new Error('Invalid layout');
    const seen = new Set<string>();
    return value
      .filter((entry): entry is HomeWidget => {
        if (
          !entry ||
          typeof entry !== 'object' ||
          !Object.prototype.hasOwnProperty.call(widgetNames, entry.kind) ||
          !['small', 'medium', 'large'].includes(entry.size) ||
          seen.has(entry.kind)
        )
          return false;
        seen.add(entry.kind);
        return true;
      })
      .map(({ kind, size }) => ({ kind, size }));
  } catch {
    return defaultWidgets.map((widget) => ({ ...widget }));
  }
}
export function moveWidget(widgets: HomeWidget[], from: number, to: number) {
  if (
    from < 0 ||
    to < 0 ||
    from >= widgets.length ||
    to >= widgets.length ||
    from === to
  )
    return widgets;
  const result = [...widgets];
  const [widget] = result.splice(from, 1);
  result.splice(to, 0, widget);
  return result;
}
