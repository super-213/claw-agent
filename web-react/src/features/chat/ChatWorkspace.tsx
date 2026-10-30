import { TaskDraftChooser, type TaskDraft } from '../tasks/TaskDraftChooser';
import { commandFromText, invocationFor, requestId, type TaskInvocation } from '../../api/tasks';
import { ArrowLeft, GitFork, Info, PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ApiError } from '../../api/client';
import { AcceptedJobError, chatApi, isViewingChat, type ChatJob } from '../../api/chat';
import { configApi } from '../../api/config';
import { sessionsApi } from '../../api/sessions';
import { skillsApi } from '../../api/skills';
import type { BranchTree, ChatStreamEvent, Message, MessageMedia } from '../../api/types';
import { BranchTreePanel } from '../branch-tree/BranchTreePanel';
import { ConfigModal } from '../settings/ConfigModal';
import { ShareModal } from '../sessions/ShareModal';
import { MobileMenuButton, SessionSidebar } from '../sessions/SessionSidebar';
import { SkillModal } from '../plugins/SkillModal';
import { UserAdminModal } from '../users/UserAdminModal';
import { Composer } from './Composer';
import { MessageList } from './MessageList';
import { RunRecoveryPanel } from './RunRecoveryPanel';
import type { BranchActionState } from './MessageRows';
import { isAdmin, selectCurrentSession, useAppStore } from '../../stores/appStore';
import { formatTokens, isImageAttachment } from '../../utils/format';
import { connectionNotice, useConnectionStatus } from '../pwa/useConnectionStatus';
import { HomeNav } from '../home/HomeNav';

type ModalKind = 'settings' | 'plugins' | 'users' | null;

interface BranchNotice {
  branchNodeId: string;
  sourceNodeId: string;
}

interface DraftSeed {
  id: number;
  text: string;
}

export function ChatWorkspace({
  initialTreeOpen = false,
  initialModal = null,
  mode = 'standalone',
  active = true,
  requestedSessionId = null,
  draftSeed = null,
  objectContext = null,
  onClose,
  onSessionChange,
}: {
  initialTreeOpen?: boolean;
  initialModal?: ModalKind;
  mode?: 'standalone' | 'overlay';
  active?: boolean;
  requestedSessionId?: string | null;
  draftSeed?: DraftSeed | null;
  objectContext?: import('../../api/chat').ChatObjectContext | null;
  onClose?: () => void;
  onSessionChange?: (sessionId: string) => void;
}) {
  const { online, disconnected } = useConnectionStatus();
  const navigate = useNavigate();
  const params = useParams();
  const currentUser = useAppStore((state) => state.currentUser);
  const sessions = useAppStore((state) => state.sessions);
  const config = useAppStore((state) => state.config);
  const currentSessionId = useAppStore((state) => state.currentSessionId);
  const currentSession = useAppStore(selectCurrentSession);
  const messages = useAppStore((state) => state.messages);
  const streams = useAppStore((state) => state.streams);
  const statusText = useAppStore((state) => state.statusText);
  const setSessions = useAppStore((state) => state.setSessions);
  const setSkills = useAppStore((state) => state.setSkills);
  const setConfig = useAppStore((state) => state.setConfig);
  const setCurrentSessionId = useAppStore((state) => state.setCurrentSessionId);
  const setMessages = useAppStore((state) => state.setMessages);
  const setSessionMessages = useAppStore((state) => state.setSessionMessages);
  const beginStream = useAppStore((state) => state.beginStream);
  const updateStream = useAppStore((state) => state.updateStream);
  const endStream = useAppStore((state) => state.endStream);
  const setStatusText = useAppStore((state) => state.setStatusText);

  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try { return localStorage.getItem('claw-chat-sidebar-collapsed') === 'true'; }
    catch { return false; }
  });
  const toggleSidebar = () => {
    const next = !sidebarCollapsed;
    setSidebarCollapsed(next);
    try { localStorage.setItem('claw-chat-sidebar-collapsed', String(next)); }
    catch { /* The toggle still works when storage is unavailable. */ }
  };
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [menuSessionId, setMenuSessionId] = useState<string | null>(null);
  const [modal, setModal] = useState<ModalKind>(initialModal);
  const [shareSessionId, setShareSessionId] = useState<string | null>(null);
  const [treeOpen, setTreeOpen] = useState(initialTreeOpen);
  const [tree, setTree] = useState<BranchTree | null>(null);
  const draftKey = currentSessionId || 'new';
  const draft = useAppStore((state) => state.chatDrafts[draftKey] || '');
  const setDraft = useCallback((value: string | ((current: string) => string)) => {
    const state = useAppStore.getState();
    state.setChatDraft(draftKey, typeof value === 'function'
      ? value(state.chatDrafts[draftKey] || '') : value);
  }, [draftKey]);
  const pendingChatMessage = useAppStore((state) => state.pendingChatMessage);
  const [readySessionId, setReadySessionId] = useState<string | null>(null);
  const [bootError, setBootError] = useState('');
  const [returnedToChat, setReturnedToChat] = useState(false);
  const [remoteJob, setRemoteJob] = useState<ChatJob | null>(null);
  const [jobActionBusy, setJobActionBusy] = useState(false);
  const [recoveryOpen, setRecoveryOpen] = useState(false);
  const refreshedJob = useRef('');
  const appliedSeed = useRef<number | null>(null);
  const [taskDraft, setTaskDraft] = useState<TaskDraft | null>(null);
  useEffect(() => setTaskDraft(null), [currentSessionId, currentUser?.id]);
  const [branchActionStates, setBranchActionStates] = useState<Record<string, BranchActionState>>({});
  const [branchNotice, setBranchNotice] = useState<BranchNotice | null>(null);

  const busySessionIds = useMemo(() => new Set(Object.keys(streams)), [streams]);
  const currentBusy = Boolean(currentSessionId && streams[currentSessionId]) || Boolean(remoteJob && ['queued', 'running', 'waiting_approval', 'waiting_user'].includes(remoteJob.status));
  const activeTreeNode = useMemo(
    () => tree?.nodes.find((node) => node.node_id === tree.active_node_id) || null,
    [tree],
  );
  const pendingBranchNodeId = activeTreeNode?.is_placeholder ? activeTreeNode.node_id : null;
  const branchCreationLocked = Boolean(pendingBranchNodeId || branchNotice);
  const standalone = mode === 'standalone';

  useEffect(() => {
    setRemoteJob(null);
    if (!active || !currentSessionId) return;
    let live = true;
    let checking = false;
    const sessionId = currentSessionId;
    const owner = currentUser?.id;
    const check = async () => {
      if (checking || !window.navigator.onLine || document.visibilityState !== 'visible') return;
      checking = true;
      try {
        const { job } = await chatApi.latestJob(sessionId);
        if (!live || useAppStore.getState().currentUser?.id !== owner || useAppStore.getState().currentSessionId !== sessionId) return;
        setRemoteJob(job);
        if (job && !['queued', 'running'].includes(job.status) && !useAppStore.getState().streams[sessionId] && refreshedJob.current !== `${job.id}:${job.status}`) {
          const detail = await sessionsApi.get(sessionId);
          if (!live || useAppStore.getState().currentUser?.id !== owner) return;
          setSessionMessages(sessionId, detail.messages || []);
          setBootError('');
          // The user may have left while the saved conversation was loading.
          if (isViewingChat(sessionId)) {
            refreshedJob.current = `${job.id}:${job.status}`;
            void chatApi.readJob(job.id).catch(() => undefined);
          }
        }
      } catch { /* Network failures retain the last known task state. */ }
      finally { checking = false; }
    };
    const refresh = () => { void check(); };
    const timer = window.setInterval(refresh, 2000);
    window.addEventListener('online', refresh);
    window.addEventListener('claw-auth-restored', refresh);
    document.addEventListener('visibilitychange', refresh);
    refresh();
    return () => {
      live = false; window.clearInterval(timer);
      window.removeEventListener('online', refresh);
      window.removeEventListener('claw-auth-restored', refresh);
      document.removeEventListener('visibilitychange', refresh);
    };
  }, [active, currentSessionId, currentUser?.id, setSessionMessages]);

  useEffect(() => {
    if (!standalone || !active) return;
    document.body.classList.add('chat-route');
    return () => {
      document.body.classList.remove('chat-route');
    };
  }, [active, standalone]);

  const loadConfig = useCallback(async () => {
    if (!isAdmin(currentUser)) return;
    const data = await configApi.get().catch(() => null);
    if (data && useAppStore.getState().currentUser?.id === currentUser?.id) setConfig(data);
  }, [currentUser, setConfig]);

  const loadSkills = useCallback(async () => {
    const owner = useAppStore.getState().currentUser?.id;
    const data = await skillsApi.list();
    if (useAppStore.getState().currentUser?.id === owner) setSkills(data.skills || []);
  }, [setSkills]);

  const loadSessions = useCallback(async () => {
    const owner = useAppStore.getState().currentUser?.id;
    const data = await sessionsApi.list();
    if (useAppStore.getState().currentUser?.id === owner) setSessions(data);
    return data;
  }, [setSessions]);

  const loadTree = useCallback(
    async (sessionId: string) => {
      const data = await sessionsApi.tree(sessionId);
      if (useAppStore.getState().currentSessionId === sessionId) setTree(data);
      return data;
    },
    [],
  );

  const openSession = useCallback(
    async (sessionId: string, options: { pushRoute?: boolean } = {}) => {
      const owner = useAppStore.getState().currentUser?.id;
      setBootError('');
      setCurrentSessionId(sessionId);
      onSessionChange?.(sessionId);
      setMenuSessionId(null);
      if (standalone && options.pushRoute !== false && params.sessionId !== sessionId) {
        navigate(`/sessions/${sessionId}`);
      }
      const detail = await sessionsApi.get(sessionId);
      if (useAppStore.getState().currentSessionId !== sessionId || useAppStore.getState().currentUser?.id !== owner) return;
      const state = useAppStore.getState();
      const cachedMessages = state.sessionMessages[sessionId];
      const nextMessages = state.streams[sessionId] && cachedMessages ? cachedMessages : detail.messages || [];
      state.setSessionMessages(sessionId, nextMessages);
      setReadySessionId(sessionId);
      setStatusText(useAppStore.getState().streams[sessionId] ? '处理中...' : '就绪');
      void loadTree(sessionId).catch(() => undefined);
      setMobileSidebarOpen(false);
    },
    [loadTree, navigate, onSessionChange, params.sessionId, setCurrentSessionId, setStatusText, standalone],
  );

  const createSession = useCallback(async () => {
    const session = await sessionsApi.create();
    await loadSessions();
    await openSession(session.id);
  }, [loadSessions, openSession]);

  useEffect(() => {
    if (!active) return;
    let mounted = true;
    const boot = async () => {
      await Promise.allSettled([loadSkills(), loadConfig()]);
      const loadedSessions = await loadSessions();
      if (!mounted) return;
      const target = requestedSessionId || params.sessionId || useAppStore.getState().currentSessionId || loadedSessions[0]?.id;
      if (target) {
        await openSession(target, { pushRoute: false });
      } else {
        await createSession();
      }
    };
    void boot().catch((error) => {
      console.warn('[ChatWorkspace] boot:', error);
      if (mounted) setBootError('暂时无法打开对话，请刷新重试。输入内容已保留。');
    });
    return () => {
      mounted = false;
    };
  }, [active, createSession, loadConfig, loadSessions, loadSkills, openSession, params.sessionId, requestedSessionId]);

  useEffect(() => {
    setTreeOpen(initialTreeOpen);
  }, [initialTreeOpen]);

  useEffect(() => {
    setModal(initialModal);
  }, [initialModal]);

  useEffect(() => {
    if (!draftSeed || !readySessionId || readySessionId !== currentSessionId || appliedSeed.current === draftSeed.id) return;
    setDraft(draftSeed.text);
    appliedSeed.current = draftSeed.id;
  }, [currentSessionId, draftSeed, readySessionId, setDraft]);

  useEffect(() => {
    setBranchActionStates({});
    setBranchNotice(null);
  }, [currentSessionId]);

  useEffect(() => {
    if (!pendingBranchNodeId && !currentBusy) {
      setBranchNotice(null);
      setBranchActionStates((current) =>
        Object.fromEntries(Object.entries(current).filter(([, state]) => state !== 'pending' && state !== 'success')),
      );
    }
  }, [currentBusy, pendingBranchNodeId]);

  const refreshCurrent = useCallback(async () => {
    await loadSessions();
    if (currentSessionId) {
      await openSession(currentSessionId, { pushRoute: false });
    }
  }, [currentSessionId, loadSessions, openSession]);

  useEffect(() => {
    if (!active) return;
    let hidden = false;
    const check = () => {
      if (document.visibilityState === 'hidden') { hidden = true; return; }
      if (!hidden || !window.navigator.onLine) return;
      hidden = false;
      if (Object.keys(useAppStore.getState().streams).length) setReturnedToChat(true);
      else void refreshCurrent().catch(() => setReturnedToChat(true));
    };
    document.addEventListener('visibilitychange', check);
    return () => document.removeEventListener('visibilitychange', check);
  }, [active, refreshCurrent]);

  const deleteSession = async (sessionId: string) => {
    if (busySessionIds.has(sessionId)) {
      alert('该会话正在生成中，请等生成完成后再删除');
      return;
    }
    const session = sessions.find((item) => item.id === sessionId);
    if (!confirm(`删除「${session?.title || '新对话'}」？此操作不可恢复。`)) return;
    await sessionsApi.delete(sessionId);
    const loaded = await loadSessions();
    if (currentSessionId === sessionId) {
      const next = loaded[0]?.id;
      if (next) await openSession(next);
      else await createSession();
    }
  };

  const copySession = async (sessionId: string) => {
    if (busySessionIds.has(sessionId) && !confirm('该会话仍在生成中，复制将只包含已保存的部分内容。继续？')) return;
    const session = await sessionsApi.copy(sessionId);
    await loadSessions();
    await openSession(session.id);
  };

  const uploadFiles = useCallback(async (files: File[], options?: import('../../api/chat').UploadOptions) => {
    const result = await chatApi.uploadMedia(files, options);
    return result.media || [];
  }, []);

  const sendMessage = useCallback(async (text: string, media: MessageMedia[] = [], invocation?: TaskInvocation) => {
    const ownerId = currentUser?.id;
    setBranchNotice(null);
    let targetSessionId = currentSessionId;
    if (!targetSessionId) {
      const created = await sessionsApi.create();
      if (useAppStore.getState().currentUser?.id !== ownerId) return false;
      targetSessionId = created.id;
      await loadSessions();
      setCurrentSessionId(targetSessionId);
      onSessionChange?.(targetSessionId);
    }
    if (!targetSessionId || streams[targetSessionId]) return false;
    if (useAppStore.getState().currentUser?.id !== ownerId) return false;

    const images = media.filter(isImageAttachment);
    const attachments = media.filter((item) => !isImageAttachment(item));
    const abortController = new AbortController();
    beginStream(targetSessionId, text, abortController);
    setStatusText('处理中...');
    setSessionMessages(targetSessionId, (currentMessages) => [
      ...currentMessages,
      {
        role: 'user',
        content: text,
        images,
        attachments,
        node_id: `optimistic-user-${Date.now()}`,
      },
    ]);

    const streamMessages = new Map<number, string>();
    let accepted = false;
    const approvalState: {
      pending: { runId: string; approvalToken: string; approved: boolean } | null;
    } = { pending: null };
    const appendSynthetic = (message: Message) => {
      if (useAppStore.getState().currentUser?.id !== ownerId) return;
      useAppStore.getState().setSessionMessages(targetSessionId as string, (currentMessages) => [...currentMessages, message]);
    };
    const updateSyntheticAssistant = (
      iteration: number,
      content: string,
      toolCalls?: Message['tool_calls'],
      uiBlocks?: Message['ui_blocks'],
      uiSummary?: string,
    ) => {
      const nodeId = `stream-assistant-${iteration}`;
      useAppStore.getState().setSessionMessages(targetSessionId as string, (currentMessages) =>
        currentMessages.map((message) => (
          message.node_id === nodeId
            ? { ...message, content, ...(toolCalls?.length ? { tool_calls: toolCalls } : {}),
              ...(uiBlocks?.length ? { ui_blocks: uiBlocks, ui_summary: uiSummary } : {}) }
            : message
        )),
      );
    };

    const handleEvent = (event: ChatStreamEvent) => {
      if (useAppStore.getState().currentUser?.id !== ownerId) return;
      if (event.type === 'job_started') {
        accepted = true;
        if (useAppStore.getState().currentSessionId === targetSessionId) setRemoteJob(event.job);
        return;
      }
      if (event.type === 'heartbeat') return;
      if (event.type === 'resource_changed') {
        window.dispatchEvent(new CustomEvent('resource_changed', { detail: event }));
        return;
      }
      if (event.type === 'ui_blocks') {
        for (const block of event.blocks) {
          const id = `stream-card-${block.card_id}`;
          useAppStore.getState().setSessionMessages(targetSessionId as string, messages =>
            messages.some(m => m.node_id === id) ? messages : [...messages, { role: 'assistant', content: '', node_id: id, ui_blocks: [block] }]);
        }
        return;
      }
      if (event.type === 'step') {
        const message = event.message || event.stage || '处理进度';
        setStatusText(message);
        updateStream(targetSessionId as string, { status: event.stage === 'saving' ? 'saving' : 'preparing' });
        appendSynthetic({ role: 'process', content: message, node_id: `process-${Date.now()}` });
        return;
      }
      if (event.type === 'model_start') {
        const iteration = event.iteration || 1;
        streamMessages.set(iteration, '');
        updateStream(targetSessionId as string, { status: 'streaming' });
        setStatusText('模型生成中...');
        appendSynthetic({ role: 'assistant', content: '', node_id: `stream-assistant-${iteration}` });
        return;
      }
      if (event.type === 'model_delta') {
        const iteration = event.iteration || 1;
        const next = `${streamMessages.get(iteration) || ''}${event.delta || ''}`;
        streamMessages.set(iteration, next);
        updateSyntheticAssistant(iteration, next);
        return;
      }
      if (event.type === 'model_done') {
        const iteration = event.iteration || 1;
        const toolCalls: Message['tool_calls'] = event.tool_calls?.map((call) => ({
          id: call.id,
          type: 'function',
          function: {
            name: call.name || 'tool',
            arguments: JSON.stringify(call.arguments || {}),
          },
        }));
        updateSyntheticAssistant(
          iteration,
          event.content || streamMessages.get(iteration) || '',
          toolCalls,
          event.ui_blocks,
          event.ui_summary,
        );
        setStatusText('解析模型回复...');
        return;
      }
      if (event.type === 'tool_start') {
        updateStream(targetSessionId as string, { status: 'running_tool' });
        const name = event.tool_call?.name || '工具';
        setStatusText(`正在调用 ${name}...`);
        appendSynthetic({
          role: 'process',
          content: `调用工具：${name}`,
          node_id: `tool-${event.tool_call?.id || Date.now()}`,
        });
        return;
      }
      if (event.type === 'task_changed' || (event.type === 'tool_result' && event.success !== false && event.tool_call?.name?.startsWith('family_'))) window.dispatchEvent(new CustomEvent('task_changed'));
      if (event.type === 'tool_result') {
        const output = event.tool_result?.output as Record<string, unknown> | undefined;
        if (event.success === false && output?.draft && !Array.isArray(output.ui_blocks)) {
          const values = Array.isArray(output.draft) ? output.draft : [output.draft];
          const items = values.filter((value): value is { title: string } => Boolean(value && typeof value.title === 'string'));
          if (items.length) setTaskDraft({ sessionId: targetSessionId as string, items, message: String(output.message || '请补充事项所需信息后再保存。') });
        } else if (event.success !== false && output?.task_changed) setTaskDraft(null);
        const name = event.tool_call?.name || '工具';
        setStatusText(event.success === false ? `${name} 执行失败` : `${name} 执行完成`);
        appendSynthetic({
          role: 'process',
          content: `${name}：${event.success === false ? '执行失败' : '执行完成'}`,
          node_id: `tool-result-${event.tool_call?.id || Date.now()}`,
        });
        return;
      }
      if (event.type === 'approval_required') {
        // Suspended pages must not approve/deny tools through a suppressed dialog.
        if (document.visibilityState !== 'visible') return;
        const runId = String(event.run_id || '');
        const approvalToken = String(event.approval_token || '');
        const name = event.tool_call?.name || '高风险工具';
        const args = JSON.stringify(event.tool_call?.arguments || {}, null, 2);
        updateStream(targetSessionId as string, { status: 'waiting_approval' });
        setStatusText('等待操作确认');
        const approved = confirm(`是否允许执行 ${name}？\n\n参数：\n${args}`);
        if (runId && approvalToken) approvalState.pending = { runId, approvalToken, approved };
        return;
      }
      if (event.type === 'error') {
        updateStream(targetSessionId as string, { status: 'error' });
        appendSynthetic({ role: 'process', content: `处理失败\n${event.message || '请求失败'}`, node_id: `error-${Date.now()}` });
      }
    };

    try {
      await chatApi.stream({ sessionId: targetSessionId, message: text, images, attachments, invocation, requestId: requestId(), objectContext: objectContext || undefined, signal: abortController.signal }, handleEvent);
      if (useAppStore.getState().currentUser?.id !== ownerId) return false;
      while (approvalState.pending) {
        const decision = approvalState.pending;
        approvalState.pending = null;
        await chatApi.approveRun(
          {
            runId: decision.runId,
            approvalToken: decision.approvalToken,
            approved: decision.approved,
            signal: abortController.signal,
          },
          handleEvent,
        );
      }
      await loadSessions();
      if (useAppStore.getState().currentSessionId === targetSessionId) {
        const detail = await sessionsApi.get(targetSessionId);
        setSessionMessages(targetSessionId, detail.messages || []);
        await loadTree(targetSessionId);
      }
      return true;
    } catch (caught) {
      console.warn('[ChatWorkspace] sendMessage:', caught);
      if (caught instanceof AcceptedJobError || accepted) {
        if (useAppStore.getState().currentUser?.id === ownerId && useAppStore.getState().currentSessionId === targetSessionId) {
          if (caught instanceof AcceptedJobError) setRemoteJob(caught.job);
          setBootError(`任务已提交至服务器，请核对任务状态；无需重复发送。${(caught as Error).message || ''}`);
        }
        return true;
      }
      if (caught instanceof ApiError && caught.status >= 400 && caught.status < 500 && useAppStore.getState().currentSessionId === targetSessionId) setDraft(text);
      appendSynthetic({ role: 'process', content: `请求失败\n${(caught as Error).message || '网络错误'}`, node_id: `error-${Date.now()}` });
      return false;
    } finally {
      endStream(targetSessionId);
      setStatusText(Object.keys(useAppStore.getState().streams).length ? '后台生成中...' : '就绪');
    }
  }, [beginStream, currentSessionId, currentUser?.id, endStream, loadSessions, loadTree, objectContext, onSessionChange, setCurrentSessionId, setDraft, setSessionMessages, setStatusText, streams, updateStream]);

  const continueJob = async () => {
    if (!remoteJob?.run_id || jobActionBusy) return;
    const job = remoteJob;
    setJobActionBusy(true);
    try {
      const events = (event: ChatStreamEvent) => { if (event.type === 'job_started') setRemoteJob(event.job); };
      if (job.status === 'waiting_approval') {
        const { runs } = await chatApi.runs(job.session_id);
        const pending = runs.find(run => run.id === job.run_id)?.pending_approval?.tool_call;
        const approved = confirm(`是否允许执行 ${pending?.name || '待确认操作'}？\n\n${JSON.stringify(pending?.arguments || {}, null, 2)}`);
        await chatApi.approveRun({ runId: job.run_id!, approvalToken: '', approved }, events);
      } else {
        await chatApi.resumeRun(job.run_id!, events);
      }
      refreshedJob.current = '';
      await refreshCurrent();
    } catch (error) {
      if (error instanceof AcceptedJobError) setRemoteJob(error.job);
      else setBootError((error as Error).message || '暂时无法继续任务。');
    } finally { setJobActionBusy(false); }
  };

  useEffect(() => {
    if (!standalone || !active || !pendingChatMessage || !readySessionId ||
      readySessionId !== currentSessionId || currentBusy) return;
    // Consume before sending so rerenders and StrictMode cannot send twice.
    if (useAppStore.getState().pendingChatMessage !== pendingChatMessage) return;
    useAppStore.getState().setPendingChatMessage(null);
    const command = commandFromText(pendingChatMessage.text);
    void sendMessage(pendingChatMessage.text, [], command ? invocationFor(command) : undefined);
  }, [active, currentBusy, currentSessionId, pendingChatMessage, readySessionId, sendMessage, standalone]);

  const createBranchFromNode = async (nodeId: string) => {
    if (!currentSessionId) return;
    if (branchCreationLocked) {
      setStatusText('新分支待输入');
      return;
    }
    setBranchActionStates((current) => ({ ...current, [nodeId]: 'pending' }));
    setStatusText('正在创建分支...');
    try {
      const result = await sessionsApi.createBranch(currentSessionId, nodeId);
      const branchNodeId = String(result.branch_node_id || '');
      setBranchActionStates((current) => ({ ...current, [nodeId]: 'success' }));
      setBranchNotice({ branchNodeId, sourceNodeId: nodeId });
      setTreeOpen(true);
      await refreshCurrent();
      await loadTree(currentSessionId).catch(() => undefined);
      setStatusText('新分支待输入');
    } catch (caught) {
      setBranchActionStates((current) => ({ ...current, [nodeId]: 'error' }));
      alert(`创建分支失败: ${(caught as Error).message || '未知错误'}`);
      setStatusText('创建分支失败');
    }
  };

  const switchBranch = async (nodeId: string) => {
    setTaskDraft(null);
    if (!currentSessionId) return;
    setBranchNotice(null);
    const result = await sessionsApi.switchBranch(currentSessionId, nodeId);
    setMessages(result.messages || []);
    await loadTree(currentSessionId);
  };

  const deleteBranch = async (nodeId: string) => {
    if (!currentSessionId) return;
    await sessionsApi.deleteBranch(currentSessionId, nodeId);
    await refreshCurrent();
  };

  const topbarTitle = currentSession?.title || '新对话';
  const tokenSummary = `总计 ${formatTokens(currentSession?.token_usage?.total_tokens)} · 工具 ${formatTokens(currentSession?.token_usage?.tool_tokens)}`;
  const branchSummary = tree ? `${tree.nodes.length} 节点` : '未载入';

  return (
    <div className={`app chat-workspace ${standalone ? `chat-standalone${sidebarCollapsed ? ' history-collapsed' : ''}` : 'chat-overlay-app'}`} data-session-id={currentSessionId || undefined}>
      {standalone && <HomeNav view="chat" />}
      {standalone ? (
        <SessionSidebar
          open={mobileSidebarOpen}
          collapsed={sidebarCollapsed}
          sessions={sessions}
          currentSessionId={currentSessionId}
          currentUser={currentUser}
          busySessionIds={busySessionIds}
          menuSessionId={menuSessionId}
          onCloseMobile={() => setMobileSidebarOpen(false)}
          onCreateSession={createSession}
          onOpenSession={openSession}
          onToggleSessionMenu={setMenuSessionId}
          onCopySession={copySession}
          onDeleteSession={deleteSession}
          onShareSession={(sessionId) => setShareSessionId(sessionId)}
        />
      ) : null}

      <main className="main">
        <div className="topbar">
          <div className="topbar-left">
            {standalone ? (
              <>
                <button className="history-panel-toggle" type="button"
                  aria-label={sidebarCollapsed ? '展开历史对话' : '收起历史对话'}
                  title={sidebarCollapsed ? '展开历史对话' : '收起历史对话'}
                  aria-expanded={!sidebarCollapsed} aria-controls="chat-session-sidebar" onClick={toggleSidebar}>
                  {sidebarCollapsed ? <PanelLeftOpen size={20} /> : <PanelLeftClose size={20} />}
                </button>
                <MobileMenuButton open={mobileSidebarOpen} onClick={() => setMobileSidebarOpen(true)} />
              </>
            ) : (
              <button className="chat-overlay-back" type="button" onClick={onClose} aria-label="返回家庭工作台">
                <ArrowLeft size={18} />
                <span>返回</span>
              </button>
            )}
            <div className="topbar-heading">
              <div className="topbar-eyebrow">{standalone ? '对话' : objectContext ? `关于：${objectContext.title}` : '家庭 Agent'}</div>
              <h1 className="topbar-title">{topbarTitle}</h1>
            </div>
          </div>
          <div className="topbar-meta">
            <details className="chat-session-info">
              <summary aria-label="会话详情" title="会话详情"><Info size={18} /></summary>
              <div className="chat-session-info-body"><strong>会话详情</strong><span>{tokenSummary}</span><span>分支树 · {branchSummary}</span></div>
            </details>
            <div className={`status-badge${disconnected ? ' disconnected' : currentBusy ? ' busy' : ''}`}
              role="status" title={disconnected ? connectionNotice : undefined}>
              <div className="dot" aria-hidden="true" />
              <span>{disconnected ? (online ? '连接中断' : '离线') : currentBusy ? '处理中...' : statusText}</span>
            </div>
            <button
              className="tree-toggle-btn"
              type="button"
              aria-label="切换分支树面板"
              aria-expanded={treeOpen}
              onClick={() => setTreeOpen((value) => !value)}
            >
              <GitFork size={18} />
            </button>
          </div>
        </div>

        {bootError && <p className="chat-navigation-notice" role="alert">{bootError}</p>}
        {remoteJob && remoteJob.status !== 'succeeded' && <div className="chat-navigation-notice" role="status">
          <span>{remoteJob.status === 'queued' || remoteJob.status === 'running' ? '服务器正在处理，离开页面后仍会继续。开启回复通知后，完成时会提醒你。' : remoteJob.status === 'waiting_approval' ? '任务等待你的操作确认。' : remoteJob.status === 'waiting_user' ? '中断前的一项操作结果需要核对，任务已暂停。' : remoteJob.error || '任务已停止，可查看已保存的对话记录。'}</span>
          {['queued', 'running'].includes(remoteJob.status) && <button type="button" disabled={jobActionBusy} onClick={() => {
            if (!remoteJob || !confirm('停止服务器上的当前任务？已完成的操作不会撤销。')) return;
            setJobActionBusy(true);
            void chatApi.cancelJob(remoteJob.id).then(() => refreshCurrent()).catch(error => setBootError(error.message)).finally(() => setJobActionBusy(false));
          }}>停止生成</button>}
          {remoteJob.run_id && ['waiting_approval', 'interrupted'].includes(remoteJob.status) && <button type="button" disabled={jobActionBusy} onClick={() => void continueJob()}>{remoteJob.status === 'waiting_approval' ? '查看并确认' : '从检查点继续'}</button>}
          {remoteJob.run_id && remoteJob.status === 'waiting_user' && <button type="button" onClick={() => setRecoveryOpen(true)}>核对操作结果</button>}
        </div>}
        {recoveryOpen && remoteJob?.run_id && <RunRecoveryPanel sessionId={remoteJob.session_id} runId={remoteJob.run_id} onClose={() => setRecoveryOpen(false)} onResolved={(cancelled) => {
          setRecoveryOpen(false);
          if (!cancelled) void continueJob();
          else void chatApi.latestJob(remoteJob.session_id).then(result => setRemoteJob(result.job));
        }} />}
        {returnedToChat && <div className="chat-navigation-notice" role="status"><span>已返回对话。可以重新读取服务器保存的结果，查看连接断开不会停止后台任务。</span><button type="button" onClick={() => {
          if (currentSessionId) useAppStore.getState().streams[currentSessionId]?.abortController?.abort();
          void refreshCurrent().then(() => setReturnedToChat(false)).catch(error => setBootError(error.message));
        }}>重新读取</button><button type="button" aria-label="关闭返回提示" onClick={() => setReturnedToChat(false)}>关闭</button></div>}
        {standalone && pendingChatMessage && (
          <div className="chat-navigation-notice" role="status">
            <span>{currentBusy ? '当前对话回复结束后将发送：' : '正在打开对话，准备发送：'}{pendingChatMessage.text}</span>
            <button type="button" onClick={() => {
              setDraft(pendingChatMessage.text);
              useAppStore.getState().setPendingChatMessage(null);
            }}>改为草稿</button>
          </div>
        )}

        <div className="main-content">
          <div className="chat-area">
            <MessageList
              messages={messages}
              conversationKey={currentSessionId}
              onCreateBranch={createBranchFromNode}
              branchActionStates={branchActionStates}
              branchCreationLocked={branchCreationLocked}
            />
            {branchNotice ? (
              <div className="branch-feedback-bar" role="status" aria-live="polite">
                <GitFork size={18} />
                <div>
                  <strong>已切到新分支</strong>
                  <span>继续输入会写入新分支；发送第一条消息前不能再次分支。</span>
                </div>
              </div>
            ) : null}
            {taskDraft && taskDraft.sessionId === currentSessionId && <TaskDraftChooser draft={taskDraft}
              onChoose={(command, body) => { setDraft(`/ ${command} ${body}`); setTaskDraft(null); }} onDismiss={() => setTaskDraft(null)} />}
            <Composer key={`${currentUser?.id}:${currentSessionId}`} disabled={currentBusy || !readySessionId || readySessionId !== currentSessionId} draft={draft} onDraftChange={setDraft} onSend={sendMessage} onUploadFiles={uploadFiles} />
          </div>
          <BranchTreePanel
            open={treeOpen}
            tree={tree}
            onClose={() => setTreeOpen(false)}
            onSelectNode={switchBranch}
            onDeleteBranch={deleteBranch}
          />
        </div>
      </main>

      {standalone && <HomeNav view="chat" mobile />}

      <ConfigModal
        open={modal === 'settings'}
        config={config}
        onClose={() => setModal(null)}
        onSaved={(nextConfig) => {
          setConfig(nextConfig);
          setStatusText('配置已保存');
          setTimeout(() => setStatusText('就绪'), 1200);
        }}
      />
      <SkillModal open={modal === 'plugins'} onClose={() => setModal(null)} onSaved={loadSkills} />
      <UserAdminModal open={modal === 'users'} onClose={() => setModal(null)} />
      <ShareModal
        open={Boolean(shareSessionId)}
        sessionId={shareSessionId}
        currentUserId={currentUser?.id}
        onClose={() => setShareSessionId(null)}
        onSaved={async () => {
          await loadSessions();
        }}
      />
    </div>
  );
}
