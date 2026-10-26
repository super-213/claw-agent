import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowRight, CalendarDays, Check } from 'lucide-react';
import { configApi } from '../../api/config';
import { homeApi, type InventoryLocation } from '../../api/home';
import { sessionsApi } from '../../api/sessions';
import { tasksApi, type TaskDefinition } from '../../api/tasks';
import type { HomeInventoryItem } from '../../api/types';
import { useDialog } from '../../components/ui/useDialog';
import { ChatWorkspace } from '../chat/ChatWorkspace';
import { ConfigModal } from '../settings/ConfigModal';
import { TaskBoard } from '../tasks/TaskBoard';
import { isAdmin, useAppStore } from '../../stores/appStore';
import { buildAttention, type Attention } from './attention';
import { InventoryView } from './InventoryView';
import { useHomeData } from './useHomeData';
import { MoreView } from './MoreView';
import { HomeNav } from './HomeNav';
import { FamilyNav } from './FamilyNav';
import { rememberFamilySection } from './familyNavigation';
import { AgentCommandBar } from './AgentCommandBar';
import { HomeWidgets } from './HomeWidgets';
import { ScheduleCalendar } from './ScheduleCalendar';
import { HomeDialog } from '../../components/ui/HomeDialog';
import type { WidgetSize } from './widgetLayout';
import { AttentionList } from './AttentionList';
import './home.css';

type ObjectContext = {
  type: 'inventory_item' | 'family_task';
  id: string;
  title: string;
  source: string;
  location?: string;
};

export function HomePage() {
  const location = useLocation();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const view = location.pathname.includes('/items')
    ? 'items'
    : location.pathname.includes('/tasks')
      ? 'tasks'
      : location.pathname.includes('/more')
        ? 'more'
        : 'today';
  const currentUser = useAppStore((s) => s.currentUser);
  const sessions = useAppStore((s) => s.sessions);
  const setSessions = useAppStore((s) => s.setSessions);
  const config = useAppStore((s) => s.config);
  const setConfig = useAppStore((s) => s.setConfig);
  const { inventories, tasks, memos, refresh } = useHomeData();
  const draft = useAppStore((s) => s.homeDraft);
  const setDraft = useAppStore((s) => s.setHomeDraft);
  const rememberHomeScroll = useAppStore((s) => s.rememberHomeScroll);
  const [notice, setNotice] = useState('');
  const [rowError, setRowError] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [small, setSmall] = useState(
    () => window.matchMedia('(max-width: 767px)').matches,
  );
  const [calendarOpen, setCalendarOpen] = useState(false);
  const calendarDestination = useRef<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [chatMounted, setChatMounted] = useState(false);
  const [chatSession, setChatSession] = useState<string | null>(null);
  const [draftSeed, setDraftSeed] = useState<{
    id: number;
    text: string;
  } | null>(null);
  const [objectContext, setObjectContext] = useState<ObjectContext | null>(
    null,
  );
  const [tasksMounted, setTasksMounted] = useState(view === 'tasks');
  useEffect(() => {
    setChatOpen(false);
    setChatMounted(false);
    setChatSession(null);
    setObjectContext(null);
    setNotice('');
    setRowError('');
  }, [currentUser?.id]);
  const scrollPath = location.pathname;
  const closeChat = useCallback(() => {
    setChatOpen(false);
    void refresh();
    window.dispatchEvent(new CustomEvent('task_changed'));
  }, [refresh]);
  const chatDialog = useDialog(chatOpen, closeChat);
  const openChat = (
    text?: string,
    sessionId?: string,
    context?: ObjectContext,
  ) => {
    setObjectContext(context || null);
    if (text !== undefined) setDraftSeed({ id: Date.now(), text });
    if (sessionId) setChatSession(sessionId);
    setChatMounted(true);
    setChatOpen(true);
  };
  const taskAgent = (task: TaskDefinition) =>
    openChat(`请帮我处理事项“${task.title}”。`, undefined, {
      type: 'family_task',
      id: task.id,
      title: task.title,
      source: location.pathname + location.search,
    });
  const itemAgent = (item: HomeInventoryItem) =>
    openChat(`请帮我处理物品“${item.name}”。`, undefined, {
      type: 'inventory_item',
      id: item.id,
      title: item.name,
      location: item.location,
      source: location.pathname + location.search,
    });
  useEffect(() => {
    document.body.classList.add('home-route');
    return () => document.body.classList.remove('home-route');
  }, []);
  useEffect(() => {
    const media = window.matchMedia('(max-width: 767px)');
    const change = () => setSmall(media.matches);
    media.addEventListener('change', change);
    return () => media.removeEventListener('change', change);
  }, []);
  useEffect(() => {
    if (view === 'tasks') setTasksMounted(true);
    if (view === 'tasks' || view === 'items') {
      rememberFamilySection(currentUser?.id || 'guest', view);
    }
  }, [currentUser?.id, view]);
  useEffect(() => {
    window.scrollTo(0, useAppStore.getState().homeScrollPositions[scrollPath] || 0);
    const remember = () => rememberHomeScroll(scrollPath, window.scrollY);
    window.addEventListener('scroll', remember, { passive: true });
    return () => window.removeEventListener('scroll', remember);
  }, [rememberHomeScroll, scrollPath]);
  const today =
    tasks.data?.today ||
    Object.values(inventories).find((query) => query.data?.today)?.data?.today;
  const allItems = Object.values(inventories).flatMap(
    (query) => query.data?.items || [],
  );
  const attention = buildAttention(
    tasks.data?.rows || [],
    allItems,
    today || '0000-01-01',
  );
  const limit = small ? 3 : 5;
  const all = params.get('attention') === 'all';
  const loading =
    tasks.isPending ||
    Object.values(inventories).some((query) => query.isPending);
  const failed =
    tasks.isError || Object.values(inventories).some((query) => query.isError);
  const exact = !loading && !failed && tasks.data?.historyComplete;
  const status = loading
    ? '正在整理需要关注的事…'
    : !exact
      ? '先看看已读取的事项'
      : attention.length
        ? `有 ${attention.length} 件事需要关注`
        : '今天暂无待处理事项';
  const dateLabel = today
    ? new Intl.DateTimeFormat('zh-CN', {
        month: 'long',
        day: 'numeric',
        weekday: 'long',
        timeZone: 'UTC',
      }).format(new Date(`${today}T12:00:00Z`))
    : '今天';
  const openSettings = () => {
    setSettingsOpen(true);
    if (isAdmin(currentUser))
      void configApi
        .get()
        .then(setConfig)
        .catch((e) => setRowError(e.message));
  };
  const go = (path: string) => {
    rememberHomeScroll(scrollPath, window.scrollY);
    navigate(path);
  };
  const run = async (entry: Attention) => {
    setBusy(entry.id);
    setRowError('');
    try {
      if (entry.kind === 'item')
        await homeApi.consumeInventoryItem(
          entry.item.id,
          undefined,
          entry.item.location as InventoryLocation,
        );
      else {
        const row = entry.row;
        const claim = !row.occurrence?.assignee_ids.length;
        await tasksApi.change(
          row.task.id,
          claim ? 'claim' : 'complete',
          {
            expected_version: claim
              ? row.task.version
              : row.occurrence!.version,
          },
          claim ? undefined : row.occurrence!.id,
        );
      }
      setNotice(
        entry.kind === 'item'
          ? `${entry.item.name} 已标记用完`
          : entry.row.occurrence?.assignee_ids.length === 0
            ? '已认领，可在事项中继续处理'
            : entry.row.occurrence!.assignee_ids.length > 1 &&
                entry.row.occurrence!.completion_mode === 'all'
              ? '已完成我的部分，其他成员的进度已保留'
              : `已完成：${entry.title}`,
      );
      await refresh();
      window.dispatchEvent(new CustomEvent('task_changed'));
    } catch (e) {
      setRowError((e as Error).message || '操作失败，请重试');
    } finally {
      setBusy(null);
    }
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const text = draft.trim();
    if (!text) return;
    useAppStore.getState().setPendingChatMessage({ text });
    setDraft('');
    go('/chat');
  };
  const renderAttention = (size: WidgetSize) => {
    const previewLimit = size === 'large' ? limit : Math.min(limit, 3);
    return (
      <section className="home-attention" aria-labelledby="attention-heading">
        <div className="home-section-head">
          <h2 id="attention-heading">需要关注</h2>
          <button
            type="button"
            onClick={() =>
              setParams(all ? {} : { attention: 'all' }, {
                replace: true,
              })
            }
          >
            {all ? '收起预览' : '查看全部'}
          </button>
        </div>
        <AttentionList
          entries={all ? attention : attention.slice(0, previewLimit)}
          actor={tasks.data?.actor || null}
          today={today || ''}
          busy={busy}
          onOpen={go}
          onRun={run}
        />
        {!loading && !attention.length && (
          <p className="home-empty">
            {failed
              ? '可从下方入口继续查看与记录。'
              : '眼下没有需要处理的事，随时记下新的安排。'}
          </p>
        )}
        {loading && !attention.length && (
          <p className="home-empty" role="status">
            正在读取家庭事项与物品…
          </p>
        )}
        {!all && attention.length > previewLimit && (
          <button
            className="home-remaining"
            type="button"
            onClick={() => setParams({ attention: 'all' }, { replace: true })}
          >
            还有 {attention.length - previewLimit} 件 · 查看全部{' '}
            <ArrowRight size={15} />
          </button>
        )}
      </section>
    );
  };
  const isToday = view === 'today';
  return (
    <main className="home-shell" aria-label="家庭 Agent">
      <div className="home-app">
        <HomeNav
          view={view}
          onLeave={() => {
            rememberHomeScroll(scrollPath, window.scrollY);
          }}
        />
        <div className="home-content">
          <header className="home-topbar">
            <div className="home-topbar-heading">
              {isToday ? (
                <>
                  <button
                    type="button"
                    className="home-date-button"
                    onClick={() => setCalendarOpen(true)}
                  >
                    <CalendarDays size={16} />
                    {dateLabel}
                  </button>
                  <h1>{status}</h1>
                </>
              ) : (
                <h1>
                  {{ items: '家庭', tasks: '家庭', more: '更多' }[view]}
                </h1>
              )}
            </div>
            <button
              type="button"
              className="home-avatar"
              onClick={() => go('/home/more?section=account')}
              aria-label="账号与设置"
            >
              {(
                currentUser?.display_name ||
                currentUser?.username ||
                '我'
              ).slice(0, 1)}
            </button>
          </header>
          {(view === 'tasks' || view === 'items') && (
            <FamilyNav section={view} onOpen={go} />
          )}
          {isToday && (
            <div className="home-today-grid">
              <div className="home-today-main">
                <AgentCommandBar
                  draft={draft}
                  onChange={setDraft}
                  onSubmit={submit}
                  onCreateTask={() => go('/home/tasks?create=1')}
                  onCreateItem={() => go('/home/items?create=1')}
                />
                <div className="home-dashboard-feedback">
                  {failed && (
                    <p className="home-error" role="alert">
                      部分数据暂时无法读取，已保留上次内容。
                      <button type="button" onClick={() => void refresh()}>
                        重试
                      </button>
                    </p>
                  )}
                  {tasks.data && !tasks.data.historyComplete && (
                    <p role="status">
                      历史整理中，当前数量尚不完整。
                      <button type="button" onClick={() => void refresh()}>
                        继续整理
                      </button>
                    </p>
                  )}
                  {rowError && <p role="alert">{rowError}</p>}
                  {notice && (
                    <p className="home-feedback" role="status">
                      <Check size={17} />
                      {notice}
                    </p>
                  )}
                </div>
                <HomeWidgets
                  key={currentUser?.id}
                  userId={currentUser?.id || 'guest'}
                  items={allItems}
                  inventoryReady={(location) =>
                    location
                      ? Boolean(
                          inventories[location as InventoryLocation]?.data,
                        )
                      : Object.values(inventories).every(
                          (query) => !!query.data,
                        )
                  }
                  inventoryFailed={(location) =>
                    location
                      ? Boolean(
                          inventories[location as InventoryLocation]?.isError,
                        )
                      : Object.values(inventories).some(
                          (query) => query.isError,
                        )
                  }
                  taskRows={tasks.data?.rows || []}
                  actor={tasks.data?.actor || null}
                  today={today || ''}
                  tasksReady={!!tasks.data}
                  tasksFailed={tasks.isError}
                  memoFailed={memos.isError}
                  memoCount={
                    memos.data?.counts.undated ??
                    (memos.isError ? null : undefined)
                  }
                  attentionCount={exact ? attention.length : undefined}
                  onOpen={go}
                  renderAttention={renderAttention}
                />
              </div>
              <ScheduleCalendar today={today} onOpen={go} />
            </div>
          )}
          {view === 'items' && <InventoryView onAgent={itemAgent} showCreateAction={false} />}
          {tasksMounted && (
            <div hidden={view !== 'tasks'}>
              <TaskBoard
                showCreateAction={false}
                key={currentUser?.id}
                createInitially={view === 'tasks' && params.has('create')}
                selectedTaskId={view === 'tasks' ? params.get('task') : null}
                preset={
                  view === 'tasks' &&
                  ['today', 'memos'].includes(params.get('preset') || '')
                    ? (params.get('preset') as 'today' | 'memos')
                    : undefined
                }
                initialView={
                  params.get('scope') === 'visible' ? 'visible' : undefined
                }
                initialPeriod={params.get('period') || undefined}
                selectedDate={params.get('date') || undefined}
                onDateClear={() => {
                  const next = new URLSearchParams(params);
                  next.delete('date');
                  next.delete('period');
                  setParams(next, { replace: true });
                }}
                onDetailClose={() => {
                  const next = new URLSearchParams(params);
                  next.delete('task');
                  next.delete('create');
                  setParams(next, { replace: true });
                }}
                onAgent={taskAgent}
              />
            </div>
          )}
          {view === 'more' && (
            <MoreView
              section={params.get('section')}
              onSettings={openSettings}
              onOpenChat={(sessionId) => go(`/sessions/${sessionId}`)}
              onNewChat={async () => {
                const session = await sessionsApi.create();
                setSessions(await sessionsApi.list());
                go(`/sessions/${session.id}`);
              }}
              sessions={sessions}
              loadSessions={() => sessionsApi.list().then(setSessions)}
            />
          )}
        </div>
        <HomeNav
          view={view}
          mobile
          onLeave={() => {
            rememberHomeScroll(scrollPath, window.scrollY);
          }}
        />
      </div>
      {chatMounted && (
        <div
          className="home-chat-overlay"
          hidden={!chatOpen}
          aria-hidden={!chatOpen}
          {...(!chatOpen ? { inert: '' } : {})}
        >
          <div className="home-chat-scrim" onClick={chatDialog.dismiss} />
          <div
            className="home-chat-layer"
            ref={chatDialog.ref}
            role="dialog"
            aria-modal={chatOpen}
            aria-label="家庭 Agent 对话"
            tabIndex={-1}
          >
            <ChatWorkspace
              mode="overlay"
              active={chatOpen}
              requestedSessionId={chatSession}
              draftSeed={draftSeed}
              objectContext={objectContext}
              onClose={chatDialog.dismiss}
              onSessionChange={setChatSession}
            />
          </div>
        </div>
      )}
      {calendarOpen && (
        <HomeDialog
          title="家庭日历"
          onClose={() => {
            setCalendarOpen(false);
            if (calendarDestination.current) {
              go(calendarDestination.current);
              calendarDestination.current = null;
            }
          }}
        >
          {(dismiss) => (
            <ScheduleCalendar
              today={today}
              compact
              onOpen={(path) => {
                calendarDestination.current = path;
                dismiss();
              }}
            />
          )}
        </HomeDialog>
      )}
      <ConfigModal
        open={settingsOpen}
        config={config}
        onClose={() => setSettingsOpen(false)}
        onSaved={(next) => {
          setConfig(next);
          setNotice('设置已保存');
        }}
      />
    </main>
  );
}
