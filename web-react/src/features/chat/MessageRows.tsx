import { GitBranch } from 'lucide-react';
import type { Message } from '../../api/types';
import {
  extractCommandFromContent,
  extractToolOutput,
  formatBytes,
  formatUsage,
  isToolCallMessage,
  isToolResultMessage,
} from '../../utils/format';
import { getMessageView, isFormatNudgeMessage, splitMixedProtocolMessage } from '../../utils/messageView';
import { MessageContent } from './MessageContent';

interface MessageRowsProps {
  messages: Message[];
  summarizedNodes?: string[];
  onCreateBranch: (nodeId: string) => void | Promise<void>;
}

interface ToolCardProps {
  iteration: number;
  command: string;
  output?: string;
  success?: boolean | null;
  returnCode?: number | null;
  running?: boolean;
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

function BranchAction({ nodeId, onCreateBranch }: { nodeId?: string; onCreateBranch: (nodeId: string) => void | Promise<void> }) {
  if (!nodeId) return null;
  return (
    <div className="message-actions">
      <button
        type="button"
        className="message-action-btn branch-btn"
        title="从此处创建分支"
        aria-label="从此处创建分支"
        onClick={(event) => {
          event.stopPropagation();
          void onCreateBranch(nodeId);
        }}
      >
        <GitBranch size={14} />
      </button>
    </div>
  );
}

function ToolCard({ iteration, command, output = '', success = null, returnCode = null, running = false }: ToolCardProps) {
  const resolved = success ?? (returnCode == null ? null : Number(returnCode) === 0);
  const text = output || '';
  const parts = [];
  if (returnCode != null) parts.push({ key: 'rc', value: String(returnCode), className: 'rc' });
  if (text) parts.push({ key: 'size', value: formatBytes(new Blob([text]).size), className: '' });

  return (
    <div className="message-row tool-call-row">
      <div className={`tool-call-card${running ? ' running' : ''}${resolved === false ? ' failure' : ''}${resolved === true ? ' success' : ''}`}>
        <div className="tool-call-head">
          <span className="tool-badge">SHELL</span>
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
}: {
  message: Message;
  index: number;
  iteration: number;
  label?: string;
  showHeader?: boolean;
  onCreateBranch: (nodeId: string) => void | Promise<void>;
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
      {isFinal ? <BranchAction nodeId={nodeId} onCreateBranch={onCreateBranch} /> : null}
    </div>
  );
}

export function MessageRows({ messages, onCreateBranch }: MessageRowsProps) {
  const rows: JSX.Element[] = [];
  let iteration = 0;

  for (let index = 0; index < messages.length; index += 1) {
    const msg = messages[index];
    if (msg.role === 'system' || isFormatNudgeMessage(msg)) continue;

    if (isToolCallMessage(msg)) {
      iteration += 1;
      if (iteration > 1) rows.push(<IterationDivider key={`iter-${index}`} iteration={iteration} />);
      const displayMessages = splitMixedProtocolMessage(msg);
      const commandMessage = displayMessages[0];
      rows.push(
        <MessageRow
          key={`${msg.node_id || index}-command`}
          message={commandMessage}
          index={index}
          iteration={iteration}
          showHeader
          onCreateBranch={onCreateBranch}
        />,
      );

      let result = null;
      if (messages[index + 1] && isToolResultMessage(messages[index + 1])) {
        result = extractToolOutput(messages[index + 1].content || '');
        index += 1;
      }
      rows.push(
        <ToolCard
          key={`${msg.node_id || index}-tool`}
          iteration={iteration}
          command={extractCommandFromContent(commandMessage.content || '')}
          output={result?.output}
          success={result?.success}
          returnCode={result?.returnCode}
        />,
      );

      displayMessages.slice(1).forEach((displayMsg, splitIndex) => {
        rows.push(
          <MessageRow
            key={`${msg.node_id || index}-split-${splitIndex}`}
            message={displayMsg}
            index={index}
            iteration={iteration}
            onCreateBranch={onCreateBranch}
          />,
        );
      });
      continue;
    }

    if (msg.role === 'assistant') {
      iteration += 1;
      if (iteration > 1) rows.push(<IterationDivider key={`iter-${index}`} iteration={iteration} />);
      splitMixedProtocolMessage(msg).forEach((displayMsg, splitIndex) => {
        rows.push(
          <MessageRow
            key={`${msg.node_id || index}-assistant-${splitIndex}`}
            message={displayMsg}
            index={index}
            iteration={iteration}
            showHeader={splitIndex === 0}
            onCreateBranch={onCreateBranch}
          />,
        );
      });
      continue;
    }

    rows.push(<MessageRow key={`${msg.node_id || index}-message`} message={msg} index={index} iteration={iteration} onCreateBranch={onCreateBranch} />);
  }

  return <>{rows}</>;
}

export function StreamingRows({
  rows,
  onCreateBranch,
}: {
  rows: Message[];
  onCreateBranch: (nodeId: string) => void | Promise<void>;
}) {
  return <MessageRows messages={rows} onCreateBranch={onCreateBranch} />;
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
