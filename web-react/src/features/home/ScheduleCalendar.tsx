import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  ArrowUpRight,
  Clock3,
} from 'lucide-react';
import { tasksApi, type TaskRow } from '../../api/tasks';
import { useAppStore } from '../../stores/appStore';

import { dayKey, monthDays, shiftMonth } from './calendarModel';
import './home-calendar.css';

const weekLabels = ['一', '二', '三', '四', '五', '六', '日'];
async function loadMonth(month: string) {
  const filters = {
    view: 'visible',
    lifecycle: 'active',
    temporal_type: 'timed',
    actionable: true,
    status: 'open',
    due_from: `${month}-01`,
    due_to: dayKey(
      new Date(
        new Date(`${shiftMonth(month, 1)}-01T12:00:00Z`).getTime() - 86400000,
      ),
    ),
    limit: '200',
  };
  const first = await tasksApi.list(filters);
  const rows = [...first.items];
  let cursor = first.next_cursor;
  while (cursor) {
    const page = await tasksApi.list({ ...filters, cursor });
    rows.push(...page.items);
    cursor = page.next_cursor;
  }
  return { rows, complete: first.history_complete };
}
export function ScheduleCalendar({
  today,
  onOpen,
  compact = false,
}: {
  today?: string;
  onOpen: (path: string) => void;
  compact?: boolean;
}) {
  const user = useAppStore((s) => s.currentUser?.id);
  const [month, setMonth] = useState(today?.slice(0, 7) || '');
  const [selected, setSelected] = useState(today || '');
  useEffect(() => {
    if (today && !month) {
      setMonth(today.slice(0, 7));
      setSelected(today);
    }
  }, [today, month]);
  const query = useQuery({
    queryKey: ['home', user, 'calendar', month],
    queryFn: () => loadMonth(month),
    enabled: Boolean(month),
    retry: false,
  });
  const days = useMemo(() => (month ? monthDays(month) : []), [month]);
  const rows = (query.data?.rows || []).filter(
    (row) =>
      row.task.lifecycle === 'active' && row.occurrence?.status === 'open',
  );
  const planned = rows
    .filter((row) => row.occurrence?.due_date === selected)
    .sort((a, b) =>
      (a.occurrence?.due_at || '99').localeCompare(
        b.occurrence?.due_at || '99',
      ),
    );
  const changeMonth = (delta: number) => {
    const next = shiftMonth(month, delta);
    setMonth(next);
    setSelected(`${next}-01`);
  };
  const dateLabel = selected
    ? new Intl.DateTimeFormat('zh-CN', {
        month: 'long',
        day: 'numeric',
        weekday: 'short',
        timeZone: 'UTC',
      }).format(new Date(`${selected}T12:00:00Z`))
    : '正在读取日期…';
  const time = (row: TaskRow) => {
    const value = row.occurrence?.due_at || '';
    return /(?:T|^)(\d{2}:\d{2})/.exec(value)?.[1] || '当天';
  };
  return (
    <aside
      className={`home-schedule${compact ? ' calendar-compact' : ''}`}
      aria-label="日程月历"
    >
      <div className="home-calendar-top">
        <CalendarDays size={21} />
        <span>家庭日历</span>
        <button
          type="button"
          aria-label="回到今天"
          disabled={!today}
          onClick={() => {
            setMonth(today!.slice(0, 7));
            setSelected(today!);
          }}
        >
          今天
        </button>
      </div>
      <div className="home-calendar-month">
        <h2>
          {month
            ? `${Number(month.slice(0, 4))} 年 ${Number(month.slice(5))} 月`
            : '日历'}
        </h2>
        <div>
          <button
            type="button"
            aria-label="上个月"
            disabled={!month}
            onClick={() => changeMonth(-1)}
          >
            <ChevronLeft size={18} />
          </button>
          <button
            type="button"
            aria-label="下个月"
            disabled={!month}
            onClick={() => changeMonth(1)}
          >
            <ChevronRight size={18} />
          </button>
        </div>
      </div>
      <div className="home-calendar-week" aria-hidden="true">
        {weekLabels.map((day) => (
          <span key={day}>{day}</span>
        ))}
      </div>
      <div className="home-calendar-days" aria-label="选择日程日期">
        {days.map((day) => (
          <button
            type="button"
            key={day}
            aria-label={day}
            aria-pressed={day === selected}
            aria-current={day === today ? 'date' : undefined}
            className={`${day.slice(0, 7) !== month ? 'outside' : ''}${day === today ? ' today' : ''}`}
            onClick={() => {
              setSelected(day);
              if (day.slice(0, 7) !== month) setMonth(day.slice(0, 7));
            }}
          >
            <span>{Number(day.slice(8))}</span>
            {rows.some((row) => row.occurrence?.due_date === day) && (
              <i aria-label="有待办日程" />
            )}
          </button>
        ))}
      </div>
      <div className="home-calendar-agenda">
        <div className="home-agenda-heading">
          <div>
            <Clock3 size={17} />
            <h3>{dateLabel}</h3>
          </div>
          <button
            type="button"
            aria-label="查看选中日期全部日程"
            disabled={!selected}
            onClick={() => onOpen(`/home/tasks?date=${selected}&scope=visible`)}
          >
            <ArrowUpRight size={19} />
          </button>
        </div>
        {query.isFetching && !query.data && <p role="status">正在读取安排…</p>}
        {query.data && !query.data.complete && (
          <p className="home-calendar-incomplete">
            历史整理中，安排可能尚不完整。
          </p>
        )}
        {query.isError && (
          <p role="alert">
            日程暂时无法更新。
            <button type="button" onClick={() => void query.refetch()}>
              重试
            </button>
          </p>
        )}
        {query.data && !query.isError && !planned.length && (
          <div className="home-agenda-empty">
            <span className="home-agenda-empty-line" />
            <p>这一天暂时没有待办日程</p>
            <button
              type="button"
              onClick={() => onOpen('/home/tasks?create=1')}
            >
              记录一个安排 <ArrowUpRight size={14} />
            </button>
          </div>
        )}
        <div className="home-agenda-list">
          {planned.slice(0, 3).map((row, index) => (
            <button
              type="button"
              className={`agenda-event event-${index}`}
              key={row.occurrence?.id || row.task.id}
              onClick={() =>
                onOpen(`/home/tasks?task=${encodeURIComponent(row.task.id)}`)
              }
            >
              <span className="agenda-time">{time(row)}</span>
              <span className="agenda-event-body">
                <strong>
                  {row.occurrence?.title_snapshot || row.task.title}
                </strong>
                <small>
                  {row.task.recurrence
                    ? '每周日程'
                    : row.task.space_type === 'household'
                      ? '家庭日程'
                      : '个人日程'}
                </small>
              </span>
            </button>
          ))}
        </div>
        {planned.length > 3 && (
          <button
            type="button"
            className="home-agenda-more"
            onClick={() => onOpen(`/home/tasks?date=${selected}&scope=visible`)}
          >
            还有 {planned.length - 3} 项安排 <ArrowUpRight size={14} />
          </button>
        )}
      </div>
    </aside>
  );
}
