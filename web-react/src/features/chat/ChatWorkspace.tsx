import { GitFork } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { authApi } from '../../api/auth';
import { chatApi } from '../../api/chat';
import { configApi } from '../../api/config';
import { sessionsApi } from '../../api/sessions';
import { skillsApi } from '../../api/skills';
import type { BranchTree, ChatStreamEvent, Message } from '../../api/types';
import { BranchTreePanel } from '../branch-tree/BranchTreePanel';
import { ConfigModal } from '../settings/ConfigModal';
import { ShareModal } from '../sessions/ShareModal';
import { MobileMenuButton, SessionSidebar } from '../sessions/SessionSidebar';
import { SkillModal } from '../plugins/SkillModal';
import { UserAdminModal } from '../users/UserAdminModal';
import { Composer } from './Composer';
import { MessageList } from './MessageList';
import type { BranchActionState } from './MessageRows';
import { isAdmin, selectCurrentSession, useAppStore } from '../../stores/appStore';
import { formatTokens } from '../../utils/format';

type ModalKind = 'settings' | 'plugins' | 'users' | null;

interface BranchNotice {
  branchNodeId: string;
  sourceNodeId: string;
}

export function ChatWorkspace({
  initialTreeOpen = false,
  initialModal = null,
}: {
  initialTreeOpen?: boolean;
  initialModal?: ModalKind;
}) {
  const navigate = useNavigate();
  const params = useParams();
  const currentUser = useAppStore((state) => state.currentUser);
  const sessions = useAppStore((state) => state.sessions);
  const skills = useAppStore((state) => state.skills);
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
  const setCurrentUser = useAppStore((state) => state.setCurrentUser);
  const beginStream = useAppStore((state) => state.beginStream);
  const updateStream = useAppStore((state) => state.updateStream);
  const endStream = useAppStore((state) => state.endStream);
  const setStatusText = useAppStore((state) => state.setStatusText);

  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [menuSessionId, setMenuSessionId] = useState<string | null>(null);
  const [modal, setModal] = useState<ModalKind>(initialModal);
  const [shareSessionId, setShareSessionId] = useState<string | null>(null);
  const [treeOpen, setTreeOpen] = useState(initialTreeOpen);
  const [tree, setTree] = useState<BranchTree | null>(null);
  const [draft, setDraft] = useState('');
  const [branchActionStates, setBranchActionStates] = useState<Record<string, BranchActionState>>({});
  const [branchNotice, setBranchNotice] = useState<BranchNotice | null>(null);

  const busySessionIds = useMemo(() => new Set(Object.keys(streams)), [streams]);
  const currentBusy = Boolean(currentSessionId && streams[currentSessionId]);
  const activeTreeNode = useMemo(
    () => tree?.nodes.find((node) => node.node_id === tree.active_node_id) || null,
    [tree],
  );
  const pendingBranchNodeId = activeTreeNode?.is_placeholder ? activeTreeNode.node_id : null;
  const branchCreationLocked = Boolean(pendingBranchNodeId || branchNotice);

  const loadConfig = useCallback(async () => {
    if (!isAdmin(currentUser)) return;
    const data = await configApi.get().catch(() => null);
    if (data) setConfig(data);
  }, [currentUser, setConfig]);

  const loadSkills = useCallback(async () => {
    const data = await skillsApi.list();
    setSkills(data.skills || []);
  }, [setSkills]);

  const loadSessions = useCallback(async () => {
    const data = await sessionsApi.list();
    setSessions(data);
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
      setCurrentSessionId(sessionId);
      setMenuSessionId(null);
      if (options.pushRoute !== false && params.sessionId !== sessionId) {
        navigate(`/sessions/${sessionId}`);
      }
      const detail = await sessionsApi.get(sessionId);
      if (useAppStore.getState().currentSessionId !== sessionId) return;
      setMessages(detail.messages || []);
      setStatusText(useAppStore.getState().streams[sessionId] ? '处理中...' : '就绪');
      void loadTree(sessionId).catch(() => undefined);
      setMobileSidebarOpen(false);
    },
    [loadTree, navigate, params.sessionId, setCurrentSessionId, setMessages, setStatusText],
  );

  const createSession = useCallback(async () => {
    const session = await sessionsApi.create();
    await loadSessions();
    await openSession(session.id);
  }, [loadSessions, openSession]);

  useEffect(() => {
    let mounted = true;
    const boot = async () => {
      await Promise.all([loadSkills(), loadConfig()]);
      const loadedSessions = await loadSessions();
      if (!mounted) return;
      const target = params.sessionId || loadedSessions[0]?.id;
      if (target) {
        await openSession(target, { pushRoute: false });
      } else {
        await createSession();
      }
    };
    void boot().catch((error) => {
      console.warn('[ChatWorkspace] boot:', error);
    });
    return () => {
      mounted = false;
    };
  }, [createSession, loadConfig, loadSessions, loadSkills, openSession, params.sessionId]);

  useEffect(() => {
    setTreeOpen(initialTreeOpen);
  }, [initialTreeOpen]);

  useEffect(() => {
    setModal(initialModal);
  }, [initialModal]);

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

  const sendMessage = async (text: string) => {
    setBranchNotice(null);
    let targetSessionId = currentSessionId;
    if (!targetSessionId) {
      const created = await sessionsApi.create();
      targetSessionId = created.id;
      await loadSessions();
      setCurrentSessionId(targetSessionId);
    }
    if (!targetSessionId || streams[targetSessionId]) return;

    const abortController = new AbortController();
    beginStream(targetSessionId, text, abortController);
    setStatusText('处理中...');
    setMessages([
      ...useAppStore.getState().messages,
      { role: 'user', content: text, node_id: `optimistic-user-${Date.now()}` },
    ]);

    const streamMessages = new Map<number, string>();
    const appendSynthetic = (message: Message) => {
      if (useAppStore.getState().currentSessionId !== targetSessionId) return;
      useAppStore.getState().setMessages([...useAppStore.getState().messages, message]);
    };
    const updateSyntheticAssistant = (iteration: number, content: string) => {
      if (useAppStore.getState().currentSessionId !== targetSessionId) return;
      const nodeId = `stream-assistant-${iteration}`;
      const next = useAppStore.getState().messages.map((message) =>
        message.node_id === nodeId ? { ...message, content } : message,
      );
      useAppStore.getState().setMessages(next);
    };

    const handleEvent = (event: ChatStreamEvent) => {
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
        updateSyntheticAssistant(iteration, event.content || streamMessages.get(iteration) || '');
        setStatusText('解析模型回复...');
        return;
      }
      if (event.type === 'command_start') {
        updateStream(targetSessionId as string, { status: 'running_tool' });
        setStatusText('执行命令...');
        appendSynthetic({
          role: 'assistant',
          content: `[命令]\n${event.command || ''}`,
          node_id: `command-${event.iteration || Date.now()}`,
        });
        return;
      }
      if (event.type === 'command_result') {
        setStatusText(event.success === false ? '命令执行失败' : '命令结果写回上下文...');
        const prefix = event.success === false ? `命令执行失败，退出码 ${event.return_code ?? -1}:` : '命令执行成功';
        appendSynthetic({
          role: 'user',
          content: `[执行完成]\n${prefix}\n${String(event.output || '').slice(0, 4000)}`,
          node_id: `command-result-${event.iteration || Date.now()}`,
        });
        return;
      }
      if (event.type === 'error') {
        updateStream(targetSessionId as string, { status: 'error' });
        appendSynthetic({ role: 'process', content: `处理失败\n${event.message || '请求失败'}`, node_id: `error-${Date.now()}` });
      }
    };

    try {
      await chatApi.stream({ sessionId: targetSessionId, message: text, signal: abortController.signal }, handleEvent);
      await loadSessions();
      if (useAppStore.getState().currentSessionId === targetSessionId) {
        const detail = await sessionsApi.get(targetSessionId);
        setMessages(detail.messages || []);
        await loadTree(targetSessionId);
      }
    } catch (caught) {
      console.warn('[ChatWorkspace] sendMessage:', caught);
      appendSynthetic({ role: 'process', content: `请求失败\n${(caught as Error).message || '网络错误'}`, node_id: `error-${Date.now()}` });
    } finally {
      endStream(targetSessionId);
      setStatusText(Object.keys(useAppStore.getState().streams).length ? '后台生成中...' : '就绪');
    }
  };

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

  const logout = async () => {
    await authApi.logout().catch(() => undefined);
    setCurrentUser(null);
    navigate('/login', { replace: true });
  };

  const insertSkill = (name: string) => {
    const prefix = `调用 ${name} skill `;
    setDraft((current) => (current.trimStart() ? prefix + current.trimStart() : prefix));
    setMobileSidebarOpen(false);
  };

  const topbarTitle = currentSession?.title || '新对话';
  const tokenSummary = `Tokens ${formatTokens(currentSession?.token_usage?.total_tokens)} · Tool ${formatTokens(currentSession?.token_usage?.tool_tokens)}`;

  return (
    <div className="app">
      <SessionSidebar
        open={mobileSidebarOpen}
        sessions={sessions}
        skills={skills}
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
        onInsertSkill={(skill) => insertSkill(skill.name)}
        onOpenSkillModal={() => setModal('plugins')}
        onReloadSkills={async () => {
          const data = await skillsApi.reload();
          setSkills(data.skills || []);
          setStatusText(`技能 ${data.skills?.length || 0}`);
          setTimeout(() => setStatusText('就绪'), 1200);
        }}
        onOpenConfig={() => setModal('settings')}
        onOpenUsers={() => setModal('users')}
        onLogout={logout}
      />

      <main className="main">
        <div className="topbar">
          <div className="topbar-left">
            <MobileMenuButton open={mobileSidebarOpen} onClick={() => setMobileSidebarOpen(true)} />
            <div className="topbar-title">{topbarTitle}</div>
          </div>
          <div className="topbar-meta">
            <div className="meta-badge">
              <span>{tokenSummary}</span>
            </div>
            <div className={`status-badge${currentBusy ? ' busy' : ''}`}>
              <div className="dot" />
              <span>{currentBusy ? '处理中...' : statusText}</span>
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

        <div className="main-content">
          <div className="chat-area">
            <MessageList
              messages={messages}
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
            <Composer disabled={currentBusy} draft={draft} onDraftChange={setDraft} onSend={sendMessage} />
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
