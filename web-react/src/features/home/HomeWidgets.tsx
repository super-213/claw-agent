import { useRef, useState, type ReactNode, type PointerEvent } from 'react';
import {
  ArrowRight,
  CalendarDays,
  GripVertical,
  LayoutGrid,
  NotebookPen,
  Package,
  Pill,
  Plus,
  Refrigerator,
  SlidersHorizontal,
  Trash2,
  TriangleAlert,
} from 'lucide-react';
import type { HomeInventoryItem } from '../../api/types';
import type { TaskRow } from '../../api/tasks';
import { HomeDialog } from '../../components/ui/HomeDialog';
import { activeInventory, locations } from './attention';
import {
  defaultWidgets,
  moveWidget,
  parseWidgetLayout,
  widgetNames,
  widgetStorageKey,
  type HomeWidget,
  type WidgetKind,
  type WidgetSize,
} from './widgetLayout';

import './home-widgets.css';

const icons = {
  today: CalendarDays,
  fridge: Refrigerator,
  medicine: Pill,
  memos: NotebookPen,
  attention: TriangleAlert,
  inventory: Package,
  pantry: Package,
};
export function HomeWidgets({
  userId,
  items,
  inventoryReady,
  inventoryFailed,
  taskRows,
  actor,
  today,
  tasksReady,
  tasksFailed = false,
  memoFailed = false,
  memoCount,
  attentionCount,
  onOpen,
  renderAttention,
}: {
  userId: string;
  items: HomeInventoryItem[];
  inventoryReady: (location?: string) => boolean;
  inventoryFailed: (location?: string) => boolean;
  taskRows: TaskRow[];
  actor: string | null;
  today: string;
  tasksReady: boolean;
  tasksFailed?: boolean;
  memoFailed?: boolean;
  memoCount: number | null | undefined;
  attentionCount: number | undefined;
  onOpen: (path: string) => void;
  renderAttention: (size: WidgetSize) => ReactNode;
}) {
  const [widgets, setWidgets] = useState<HomeWidget[]>(() => {
    try {
      return parseWidgetLayout(localStorage.getItem(widgetStorageKey(userId)));
    } catch {
      return defaultWidgets.map((widget) => ({ ...widget }));
    }
  });
  const [editing, setEditing] = useState(false);
  const [catalog, setCatalog] = useState(false);
  const [feedback, setFeedback] = useState('');
  const drag = useRef<{
    kind: WidgetKind;
    x: number;
    y: number;
    moved: boolean;
  } | null>(null);
  const [offset, setOffset] = useState<{
    kind: WidgetKind;
    x: number;
    y: number;
  } | null>(null);
  const update = (next: HomeWidget[], message = '布局已保存') => {
    setWidgets(next);
    try {
      localStorage.setItem(widgetStorageKey(userId), JSON.stringify(next));
      setFeedback(message);
    } catch {
      setFeedback('布局已更新；当前浏览器无法保存，下次打开将恢复默认。');
    }
  };
  const finishDrag = (event: PointerEvent<HTMLButtonElement>) => {
    const source = drag.current;
    if (source?.moved) {
      const target = document
        .elementFromPoint(event.clientX, event.clientY)
        ?.closest<HTMLElement>('[data-widget-kind]')?.dataset.widgetKind;
      if (target)
        update(
          moveWidget(
            widgets,
            widgets.findIndex((w) => w.kind === source.kind),
            widgets.findIndex((w) => w.kind === target),
          ),
          '小组件顺序已保存',
        );
    }
    drag.current = null;
    setOffset(null);
  };
  const metric = (kind: WidgetKind) => {
    if (kind === 'today') {
      const count = taskRows.filter(
        (row) =>
          row.task.lifecycle === 'active' &&
          row.occurrence?.status === 'open' &&
          row.occurrence.due_date === today &&
          (row.occurrence.assignee_ids.includes(actor || '') ||
            row.task.related_member_ids.includes(actor || '')),
      ).length;
      return {
        value: tasksReady ? count : undefined,
        unit: '件',
        detail: tasksFailed
          ? '日程更新失败，点击查看'
          : tasksReady
            ? count
              ? '今天由我参与处理'
              : '今天没有待办安排'
            : '正在读取日程',
        path: '/home/tasks?preset=today',
      };
    }
    if (kind === 'memos')
      return {
        value: memoCount,
        unit: '件',
        detail: memoFailed
          ? '备忘更新失败，点击查看'
          : memoCount === undefined
            ? '正在读取备忘'
            : memoCount === null
              ? '暂时无法读取备忘'
              : '无日期的待办，慢慢完成',
        path: '/home/tasks?preset=memos',
      };
    const location = kind === 'inventory' ? undefined : kind;
    const visible = items.filter(
      (item) =>
        activeInventory(item) && (!location || item.location === location),
    );
    return {
      value: inventoryReady(location) ? visible.length : undefined,
      unit: '项',
      detail: inventoryFailed(location)
        ? '更新失败，点击查看'
        : inventoryReady(location)
          ? visible.length
            ? '已记录的在库物品'
            : '添加第一件物品'
          : '正在读取物品',
      path: `/home/items?location=${location || 'fridge'}`,
      items: visible,
    };
  };
  return (
    <section
      className={`home-widget-section${editing ? ' is-editing' : ''}`}
      aria-label="我的小组件"
    >
      <div className="home-widget-heading">
        <div>
          <LayoutGrid size={17} />
          <h2>我的小组件</h2>
        </div>
        <div>
          {editing && (
            <button type="button" onClick={() => setCatalog(true)}>
              <Plus size={16} />
              添加组件
            </button>
          )}
          <button
            type="button"
            aria-pressed={editing}
            onClick={() => setEditing(!editing)}
          >
            <SlidersHorizontal size={16} />
            {editing ? '完成' : '自定义'}
          </button>
        </div>
      </div>
      {editing && (
        <div className="home-widget-edit-hint">
          <span>拖动手柄或使用方向键排序，布局保存在此设备。</span>
          <button
            type="button"
            onClick={() =>
              update(
                defaultWidgets.map((widget) => ({ ...widget })),
                '已恢复默认布局',
              )
            }
          >
            恢复默认
          </button>
        </div>
      )}
      <p className="sr-only" role="status">
        {feedback}
      </p>
      <div className="home-widget-grid">
        {widgets.map((widget, index) => {
          const Icon = icons[widget.kind];
          const data = metric(widget.kind);
          const attention = widget.kind === 'attention';
          const dragging = offset?.kind === widget.kind;
          return (
            <article
              key={widget.kind}
              data-widget-kind={widget.kind}
              className={`home-widget widget-${widget.kind} widget-${widget.size}${dragging ? ' is-dragging' : ''}`}
              style={
                dragging
                  ? {
                      transform: `translate(${offset.x}px, ${offset.y}px)`,
                      zIndex: 4,
                    }
                  : undefined
              }
            >
              {editing && (
                <div className="home-widget-tools">
                  <button
                    type="button"
                    className="home-widget-grip"
                    aria-label={`移动${widgetNames[widget.kind]}，使用方向键排序`}
                    onPointerDown={(event) => {
                      if (event.button !== 0) return;
                      event.currentTarget.setPointerCapture(event.pointerId);
                      drag.current = {
                        kind: widget.kind,
                        x: event.clientX,
                        y: event.clientY,
                        moved: false,
                      };
                    }}
                    onPointerMove={(event) => {
                      if (!drag.current || drag.current.kind !== widget.kind)
                        return;
                      const x = event.clientX - drag.current.x,
                        y = event.clientY - drag.current.y;
                      if (Math.hypot(x, y) > 8 || drag.current.moved) {
                        drag.current.moved = true;
                        setOffset({ kind: widget.kind, x, y });
                      }
                    }}
                    onPointerUp={finishDrag}
                    onPointerCancel={() => {
                      drag.current = null;
                      setOffset(null);
                    }}
                    onKeyDown={(event) => {
                      if (
                        ![
                          'ArrowLeft',
                          'ArrowUp',
                          'ArrowRight',
                          'ArrowDown',
                        ].includes(event.key)
                      )
                        return;
                      event.preventDefault();
                      update(
                        moveWidget(
                          widgets,
                          index,
                          index +
                            (['ArrowLeft', 'ArrowUp'].includes(event.key)
                              ? -1
                              : 1),
                        ),
                        '小组件顺序已保存',
                      );
                    }}
                  >
                    <GripVertical size={18} />
                  </button>
                  <select
                    aria-label={`${widgetNames[widget.kind]}尺寸`}
                    value={widget.size}
                    onChange={(event) =>
                      update(
                        widgets.map((w) =>
                          w.kind === widget.kind
                            ? { ...w, size: event.target.value as WidgetSize }
                            : w,
                        ),
                      )
                    }
                  >
                    <option value="small">小</option>
                    <option value="medium">中</option>
                    <option value="large">大</option>
                  </select>
                  <button
                    type="button"
                    aria-label={`移除${widgetNames[widget.kind]}`}
                    onClick={() =>
                      update(
                        widgets.filter((w) => w.kind !== widget.kind),
                        '组件已移除，可从添加组件中恢复',
                      )
                    }
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              )}
              <div
                className="home-widget-content"
                {...(editing ? { inert: '' } : {})}
              >
                {attention && widget.size !== 'small' ? (
                  renderAttention(widget.size)
                ) : (
                  <>
                    <button
                      className="home-widget-metric"
                      type="button"
                      onClick={() =>
                        onOpen(attention ? '/home?attention=all' : data.path)
                      }
                      disabled={editing}
                    >
                      <span className="home-widget-label">
                        <Icon size={21} />
                        <span>{widgetNames[widget.kind]}</span>
                        <ArrowRight size={15} />
                      </span>
                      <span className="home-widget-number">
                        <strong>
                          {(attention ? attentionCount : data.value) ?? '—'}
                        </strong>
                        <small>{attention ? '件' : data.unit}</small>
                      </span>
                      <span className="home-widget-caption">
                        {attention ? '待处理事项与临期物品' : data.detail}
                      </span>
                    </button>
                    {widget.size !== 'small' &&
                      'items' in data &&
                      !!data.items?.length && (
                        <div className="home-widget-item-list">
                          {data.items
                            .slice(0, widget.size === 'large' ? 5 : 3)
                            .map((item) => (
                              <button
                                key={`${item.location}-${item.id}`}
                                type="button"
                                disabled={editing}
                                onClick={() =>
                                  onOpen(
                                    `/home/items?location=${item.location}&item=${encodeURIComponent(item.id)}`,
                                  )
                                }
                              >
                                <span>
                                  {item.name}
                                  <small>
                                    {locations[
                                      item.location as keyof typeof locations
                                    ] || item.location}
                                  </small>
                                </span>
                                <strong>
                                  {item.quantity ?? '—'}
                                  <small>{item.unit}</small>
                                </strong>
                              </button>
                            ))}
                        </div>
                      )}
                  </>
                )}
              </div>
            </article>
          );
        })}
      </div>
      {!widgets.length && (
        <div className="home-widget-empty">
          <LayoutGrid size={26} />
          <p>把常用的家庭信息放在这里。</p>
          <button type="button" onClick={() => setCatalog(true)}>
            <Plus size={17} />
            添加小组件
          </button>
        </div>
      )}
      {catalog && (
        <HomeDialog title="添加小组件" onClose={() => setCatalog(false)} swipeToClose>
          <div className="home-widget-catalog">
            {(Object.keys(widgetNames) as WidgetKind[]).map((kind) => {
              const Icon = icons[kind];
              const added = widgets.some((widget) => widget.kind === kind);
              return (
                <button
                  type="button"
                  key={kind}
                  disabled={added}
                  onClick={() =>
                    update(
                      [
                        ...widgets,
                        {
                          kind,
                          size: ['attention', 'inventory'].includes(kind)
                            ? 'medium'
                            : 'small',
                        },
                      ],
                      `已添加${widgetNames[kind]}`,
                    )
                  }
                >
                  <Icon size={24} />
                  <span>{widgetNames[kind]}</span>
                  <small>{added ? '已添加' : '添加 +'}</small>
                </button>
              );
            })}
          </div>
        </HomeDialog>
      )}
    </section>
  );
}
