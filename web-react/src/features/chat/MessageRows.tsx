import { Check, GitBranch, Loader2 } from 'lucide-react';
import type { Message } from '../../api/types';
import { formatBytes, formatUsage } from '../../utils/format';
import { getMessageView } from '../../utils/messageView';
import { MessageContent } from './MessageContent';

interface MessageRowsProps {
  messages: Message[];
  summarizedNodes?: string[];
  onCreateBranch: (nodeId: string) => void | Promise<void>;
  branchActionStates?: Record<string, BranchActionState>;
  branchCreationLocked?: boolean;
}

export type BranchActionState = 'idle' | 'pending' | 'success' | 'error';

interface ToolCardProps {
  iteration: number;
  command: string;
  output?: string;
  success?: boolean | null;
  returnCode?: number | null;
  running?: boolean;
  badge?: string;
}

function ProtocolFlow({ flow }: { flow: NonNullable<ReturnType<typeof getMessageView>['flow']> }) {
  return (
    <div className={`protocol-flow${flow.reverse ? ' reverse' : ''}`}>
      <span className="protocol-endpoint">{flow.from}</span>
      <span className="protocol-wire">
        <span className="protocol-packet">{flow.packet}</span>
      </span>
      <span className="protocol-endpoint">{flow.to}</span>
    </div>
  );
}

const isEmptyBranchPlaceholder = (message: Message): boolean =>
  message.role === 'user' &&
  !(message.content || '').trim() &&
  !message.images?.length &&
  !message.attachments?.length &&
  Boolean(message.node_id && message.parent_id);

function LlmHeader({
  iteration,
  model = 'model',
  messageCount = 0,
  stateText = 'done',
  done = true,
}: {
  iteration: number;
  model?: string;
  messageCount?: number;
  stateText?: string;
  done?: boolean;
}) {
  return (
    <div className={`llm-req-header${done ? ' done' : ''}`}>
      <span className="req-tag">LLM</span>
      <span className="req-iter">#{iteration}</span>
      <span className="req-model">{model}</span>
      <span className="req-msgs">{messageCount} msgs</span>
      <span className="req-state">
        <span className="dot" />
        <span className="req-state-text">{stateText}</span>
      </span>
    </div>
  );
}

function BranchAction({
  nodeId,
  onCreateBranch,
  state = 'idle',
  locked = false,
}: {
  nodeId?: string;
  onCreateBranch: (nodeId: string) => void | Promise<void>;
  state?: BranchActionState;
  locked?: boolean;
}) {
  if (!nodeId) return null;
  const disabled = locked || state === 'pending' || state === 'success';
  const title = locked
    ? '新分支尚未对话，发送一条消息后才能继续分支'
    : state === 'pending'
      ? '正在创建分支'
      : state === 'success'
        ? '已切到新分支'
        : state === 'error'
          ? '创建分支失败，点击重试'
          : '从此处创建分支';
  return (
    <div className={`message-actions${state !== 'idle' ? ' always-visible' : ''}`}>
      <button
        type="button"
        className={`message-action-btn branch-btn is-${locked ? 'locked' : state}`}
        title={title}
        aria-label={title}
        disabled={disabled}
        onClick={(event) => {
          event.stopPropagation();
          if (disabled) return;
          void onCreateBranch(nodeId);
        }}
      >
        <span className="action-icon">
          {state === 'pending' ? <Loader2 size={14} /> : state === 'success' ? <Check size={14} /> : <GitBranch size={14} />}
        </span>
      </button>
    </div>
  );
}

function ToolCard({ iteration, command, output = '', success = null, returnCode = null, running = false, badge = 'SHELL' }: ToolCardProps) {
  const resolved = success ?? (returnCode == null ? null : Number(returnCode) === 0);
  const text = output || '';
  const parts = [];
  if (returnCode != null) parts.push({ key: 'rc', value: String(returnCode), className: 'rc' });
  if (text) parts.push({ key: 'size', value: formatBytes(new Blob([text]).size), className: '' });

  return (
    <div className="message-row tool-call-row">
      <div className={`tool-call-card${running ? ' running' : ''}${resolved === false ? ' failure' : ''}${resolved === true ? ' success' : ''}`}>
        <div className="tool-call-head">
          <span className="tool-badge">{badge}</span>
          <span className="tool-iter">#{iteration}</span>
          <span className="tool-status">
            <span className="dot" />
            <span className="tool-status-text">{running ? 'running' : resolved === false ? 'failed' : 'done'}</span>
          </span>
        </div>
        <div className="tool-call-command">{command}</div>
        {text ? (
          <div className="tool-call-output-wrap open">
            <button type="button" className="tool-call-output-toggle">
              <span className="toggle-label">output</span>
              <span className="caret">▾</span>
            </button>
            <pre className="tool-call-output">{text}</pre>
          </div>
        ) : null}
        {parts.length ? (
          <div className="tool-call-meta">
            {parts.map((part) => (
              <span key={part.key}>
                <span className="meta-key">{part.key}</span>
                <span className={`meta-val ${part.className}`}>{part.value}</span>
              </span>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function IterationDivider({ iteration }: { iteration: number }) {
  return (
    <div className="iteration-divider">
      <span>iteration #{iteration}</span>
    </div>
  );
}

function MessageRow({
  message,
  index,
  iteration,
  label,
  showHeader,
  onCreateBranch,
  branchActionStates,
  branchCreationLocked,
}: {
  message: Message;
  index: number;
  iteration: number;
  label?: string;
  showHeader?: boolean;
  onCreateBranch: (nodeId: string) => void | Promise<void>;
  branchActionStates?: Record<string, BranchActionState>;
  branchCreationLocked?: boolean;
}) {
  const view = getMessageView(message);
  const isFinal = view.role === 'final';
  const contextNodes = new Set(Array.isArray(message.context_nodes) ? message.context_nodes : []);
  const nodeId = message.node_id;
  const highlightClass = contextNodes.has(nodeId || '') ? ' context-highlight context-highlight-full' : '';

  return (
    <div
      className={`message-row ${view.role}-row${highlightClass}`}
      data-node-id={nodeId || undefined}
      data-branchable={isFinal && nodeId ? 'true' : undefined}
    >
      {showHeader ? <LlmHeader iteration={iteration} messageCount={index} /> : <div className="msg-label">{label || view.label}</div>}
      {view.flow ? <ProtocolFlow flow={view.flow} /> : null}
      <div className={`message ${view.role}`}>
        <MessageContent message={message} />
      </div>
      {formatUsage(message.usage) ? <div className="msg-usage">{formatUsage(message.usage)}</div> : null}
      {isFinal ? (
        <BranchAction
          nodeId={nodeId}
          onCreateBranch={onCreateBranch}
          state={(nodeId && branchActionStates?.[nodeId]) || 'idle'}
          locked={Boolean(branchCreationLocked && nodeId && branchActionStates?.[nodeId] !== 'success')}
        />
      ) : null}
    </div>
  );
}

export function MessageRows({ messages, onCreateBranch, branchActionStates, branchCreationLocked = false }: MessageRowsProps) {
  const rows: JSX.Element[] = [];
  let iteration = 0;

  for (let index = 0; index < messages.length; index += 1) {
    const msg = messages[index];
    if (isEmptyBranchPlaceholder(msg)) continue;
    if (msg.role === 'system') continue;

    if (msg.tool_calls?.length) {
      iteration += 1;
      if (iteration > 1) rows.push(<IterationDivider key={`iter-${index}`} iteration={iteration} />);
      const results = new Map<string, Message>();
      let resultIndex = index + 1;
      while (messages[resultIndex]?.role === 'tool') {
        const resultMessage = messages[resultIndex];
        if (resultMessage.tool_call_id) results.set(resultMessage.tool_call_id, resultMessage);
        resultIndex += 1;
      }
      msg.tool_calls.forEach((call, callIndex) => {
        const name = call.function?.name || msg.name || 'tool';
        const args = call.function?.arguments || '{}';
        const resultMessage = call.id ? results.get(call.id) : undefined;
        let success: boolean | null = null;
        if (resultMessage?.content) {
          try {
            success = JSON.parse(resultMessage.content).status === 'success';
          } catch {
            success = null;
          }
        }
        rows.push(
          <ToolCard
            key={`${msg.node_id || index}-native-tool-${call.id || callIndex}`}
            iteration={iteration}
            command={`${name} ${args}`}
            output={resultMessage?.content || ''}
            success={success}
            badge="TOOL"
          />,
        );
      });
      index = resultIndex - 1;
      continue;
    }

    if (msg.role === 'tool') continue;

    if (msg.role === 'assistant') {
      iteration += 1;
      if (iteration > 1) rows.push(<IterationDivider key={`iter-${index}`} iteration={iteration} />);
      rows.push(
        <MessageRow
          key={`${msg.node_id || index}-assistant`}
          message={msg}
          index={index}
          iteration={iteration}
          showHeader
          onCreateBranch={onCreateBranch}
          branchActionStates={branchActionStates}
          branchCreationLocked={branchCreationLocked}
        />,
      );
      continue;
    }

    rows.push(
      <MessageRow
        key={`${msg.node_id || index}-message`}
        message={msg}
        index={index}
        iteration={iteration}
        onCreateBranch={onCreateBranch}
        branchActionStates={branchActionStates}
        branchCreationLocked={branchCreationLocked}
      />,
    );
  }

  return <>{rows}</>;
}

export function StreamingRows({
  rows,
  onCreateBranch,
  branchActionStates,
  branchCreationLocked,
}: {
  rows: Message[];
  onCreateBranch: (nodeId: string) => void | Promise<void>;
  branchActionStates?: Record<string, BranchActionState>;
  branchCreationLocked?: boolean;
}) {
  return (
    <MessageRows
      messages={rows}
      onCreateBranch={onCreateBranch}
      branchActionStates={branchActionStates}
      branchCreationLocked={branchCreationLocked}
    />
  );
}

export function RunningToolCard({ iteration, command }: { iteration: number; command: string }) {
  return <ToolCard iteration={iteration} command={command} running />;
}

export function ProcessRow({ title, detail }: { title: string; detail?: string }) {
  return (
    <div className="message-row process-row">
      <div className="msg-label">// Model Process</div>
      <div className="message process">{detail ? `${title}\n${detail}` : title}</div>
    </div>
  );
}

export function StreamingAssistantRow({ iteration, content }: { iteration: number; content: string }) {
  return (
    <div className="message-row assistant-row streaming-row">
      <LlmHeader iteration={iteration} stateText="streaming" done={false} />
      <div className="message assistant streaming">
        <div className="message-text">{content}</div>
      </div>
    </div>
  );
}
